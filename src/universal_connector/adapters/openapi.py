"""OpenAPI 3.x and Swagger 2.0 adapter.

Parses the document, resolves local ``$ref`` pointers, infers the base URL, and
emits one `Operation` per path/method combination. Security schemes become
`AuthScheme` entries with a best-effort ``credential_ref`` guess so users can
supply secrets via environment variables.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from universal_connector.adapters.base import AdapterError, SpecAdapter
from universal_connector.models import (
    AuthScheme,
    AuthType,
    LoadedApi,
    Operation,
    Parameter,
    ParameterLocation,
    Protocol,
)

_HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
_MAX_REF_DEPTH = 12


def _load(content: str) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        try:
            import yaml

            data = yaml.safe_load(content)
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(f"Could not parse OpenAPI spec: {exc}") from exc
    if not isinstance(data, dict):
        raise AdapterError("OpenAPI spec must be a JSON/YAML object.")
    return data


def _resolve_ref(ref: str, root: dict[str, Any]) -> Any:
    """Resolve a local ``#/a/b/c`` JSON pointer against the root document."""
    if not ref.startswith("#/"):
        # External refs are intentionally not fetched (security / determinism).
        return {}
    node: Any = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return {}
    return node


def _resolve_schema(schema: Any, root: dict[str, Any], depth: int = 0) -> Any:
    """Recursively inline local ``$ref`` pointers, guarding against cycles."""
    if depth > _MAX_REF_DEPTH:
        return {}
    if isinstance(schema, dict):
        if "$ref" in schema and isinstance(schema["$ref"], str):
            resolved = _resolve_ref(schema["$ref"], root)
            return _resolve_schema(resolved, root, depth + 1)
        return {k: _resolve_schema(v, root, depth + 1) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_resolve_schema(item, root, depth + 1) for item in schema]
    return schema


def _guess_credential_ref(api_name: str, scheme_name: str) -> str:
    base = "".join(c if c.isalnum() else "_" for c in api_name.upper()).strip("_")
    suffix = "".join(c if c.isalnum() else "_" for c in scheme_name.upper()).strip("_")
    return f"{base}_{suffix}" if base else suffix


class OpenAPIAdapter(SpecAdapter):
    protocol = Protocol.OPENAPI

    def parse(
        self,
        content: str,
        source: str,
        name: str,
        base_url: str | None = None,
    ) -> tuple[LoadedApi, list[Operation]]:
        root = _load(content)
        is_v3 = "openapi" in root
        info = root.get("info", {}) if isinstance(root.get("info"), dict) else {}

        resolved_base = base_url or self._infer_base_url(root, source, is_v3)
        auth_schemes = self._parse_security_schemes(root, name, is_v3)
        global_security = self._security_names(root.get("security"))

        operations: list[Operation] = []
        paths = root.get("paths", {})
        if not isinstance(paths, dict):
            paths = {}

        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            shared_params = path_item.get("parameters", [])
            for method, op_spec in path_item.items():
                if method.lower() not in _HTTP_METHODS or not isinstance(op_spec, dict):
                    continue
                operations.append(
                    self._build_operation(
                        method=method,
                        path=path,
                        op_spec=op_spec,
                        shared_params=shared_params,
                        root=root,
                        api_name=name,
                        base_url=resolved_base,
                        is_v3=is_v3,
                        auth_schemes=auth_schemes,
                        global_security=global_security,
                    )
                )

        host = urlsplit(resolved_base).hostname
        loaded = LoadedApi(
            name=name,
            protocol=Protocol.OPENAPI,
            base_url=resolved_base,
            title=info.get("title"),
            version=info.get("version"),
            spec_source=source,
            hosts=[host.lower()] if host else [],
            auth_schemes=list(auth_schemes.values()),
        )
        return loaded, operations

    # --- helpers -------------------------------------------------------

    def _infer_base_url(self, root: dict[str, Any], source: str, is_v3: bool) -> str:
        if is_v3:
            servers = root.get("servers")
            if isinstance(servers, list) and servers and isinstance(servers[0], dict):
                url = servers[0].get("url", "")
                if url.startswith("http"):
                    return url.rstrip("/")
                # Relative server URL: combine with the source origin.
                if source.startswith("http"):
                    parts = urlsplit(source)
                    return urlunsplit((parts.scheme, parts.netloc, url.rstrip("/"), "", ""))
        else:  # Swagger 2.0
            schemes = root.get("schemes") or ["https"]
            host = root.get("host")
            base_path = root.get("basePath", "")
            if host:
                return f"{schemes[0]}://{host}{base_path}".rstrip("/")

        if source.startswith("http"):
            parts = urlsplit(source)
            return urlunsplit((parts.scheme, parts.netloc, "", "", "")).rstrip("/")
        raise AdapterError(
            "Could not infer base URL from spec; pass base_url explicitly."
        )

    def _parse_security_schemes(
        self, root: dict[str, Any], api_name: str, is_v3: bool
    ) -> dict[str, AuthScheme]:
        if is_v3:
            components = root.get("components", {})
            raw = components.get("securitySchemes", {}) if isinstance(components, dict) else {}
        else:
            raw = root.get("securityDefinitions", {})
        if not isinstance(raw, dict):
            return {}

        schemes: dict[str, AuthScheme] = {}
        for key, defn in raw.items():
            if not isinstance(defn, dict):
                continue
            schemes[key] = self._to_auth_scheme(key, defn, api_name)
        return schemes

    def _to_auth_scheme(self, key: str, defn: dict[str, Any], api_name: str) -> AuthScheme:
        raw_type = (defn.get("type") or "").lower()
        cred_ref = _guess_credential_ref(api_name, key)

        if raw_type == "apikey":
            loc = defn.get("in", "header").lower()
            location = ParameterLocation.QUERY if loc == "query" else (
                ParameterLocation.COOKIE if loc == "cookie" else ParameterLocation.HEADER
            )
            return AuthScheme(
                type=AuthType.API_KEY,
                name=defn.get("name", "Authorization"),
                location=location,
                credential_ref=cred_ref,
            )
        if raw_type == "http":
            scheme = (defn.get("scheme") or "").lower()
            if scheme == "basic":
                return AuthScheme(type=AuthType.BASIC, scheme="basic", credential_ref=cred_ref)
            return AuthScheme(type=AuthType.BEARER, scheme="bearer", credential_ref=cred_ref)
        if raw_type in {"oauth2", "openidconnect"}:
            flows = defn.get("flows", {}) if isinstance(defn.get("flows"), dict) else {}
            token_url = None
            scopes: list[str] = []
            for flow in flows.values():
                if isinstance(flow, dict):
                    token_url = token_url or flow.get("tokenUrl")
                    scopes.extend((flow.get("scopes") or {}).keys())
            return AuthScheme(
                type=AuthType.OAUTH2,
                credential_ref=cred_ref,
                token_url=token_url or defn.get("tokenUrl"),
                scopes=sorted(set(scopes)),
                flows=flows,
            )
        if raw_type == "basic":  # Swagger 2.0
            return AuthScheme(type=AuthType.BASIC, scheme="basic", credential_ref=cred_ref)
        return AuthScheme(type=AuthType.NONE)

    def _security_names(self, security: Any) -> list[str]:
        names: list[str] = []
        if isinstance(security, list):
            for req in security:
                if isinstance(req, dict):
                    names.extend(req.keys())
        return names

    def _build_operation(
        self,
        *,
        method: str,
        path: str,
        op_spec: dict[str, Any],
        shared_params: list[Any],
        root: dict[str, Any],
        api_name: str,
        base_url: str,
        is_v3: bool,
        auth_schemes: dict[str, AuthScheme],
        global_security: list[str],
    ) -> Operation:
        raw_op_id = op_spec.get("operationId") or self._synth_op_id(method, path)
        op_id = f"{api_name}.{raw_op_id}"

        parameters: list[Parameter] = []
        request_body_schema: dict[str, Any] | None = None

        all_params = list(shared_params) + list(op_spec.get("parameters", []))
        for raw in all_params:
            param = self._parse_parameter(raw, root, is_v3)
            if param is not None:
                if param.location == ParameterLocation.BODY:
                    request_body_schema = param.schema_ or {"type": "object"}
                else:
                    parameters.append(param)

        if is_v3 and isinstance(op_spec.get("requestBody"), (dict,)):
            request_body_schema = self._parse_request_body(op_spec["requestBody"], root)

        response_schema = self._parse_responses(op_spec.get("responses", {}), root)

        op_security = self._security_names(op_spec.get("security"))
        applicable = op_security or global_security
        auth = [auth_schemes[n] for n in applicable if n in auth_schemes]

        return Operation(
            operation_id=op_id,
            api_name=api_name,
            protocol=Protocol.OPENAPI,
            method=method.upper(),
            path=path,
            base_url=base_url,
            summary=op_spec.get("summary"),
            description=op_spec.get("description"),
            tags=list(op_spec.get("tags", [])),
            parameters=parameters,
            request_body_schema=request_body_schema,
            response_schema=response_schema,
            auth=auth,
        )

    def _synth_op_id(self, method: str, path: str) -> str:
        slug = "".join(c if c.isalnum() else "_" for c in path).strip("_")
        return f"{method.lower()}_{slug}" if slug else method.lower()

    def _parse_parameter(
        self, raw: Any, root: dict[str, Any], is_v3: bool
    ) -> Parameter | None:
        if isinstance(raw, dict) and "$ref" in raw:
            raw = _resolve_ref(raw["$ref"], root)
        if not isinstance(raw, dict) or "name" not in raw:
            return None

        loc_raw = (raw.get("in") or "query").lower()
        if loc_raw == "body":  # Swagger 2.0 body parameter
            schema = _resolve_schema(raw.get("schema", {}), root)
            return Parameter(
                name="body",
                location=ParameterLocation.BODY,
                required=bool(raw.get("required", False)),
                description=raw.get("description"),
                schema=schema if isinstance(schema, dict) else {},
            )
        if loc_raw == "formdata":
            loc = ParameterLocation.BODY
        else:
            loc = {
                "path": ParameterLocation.PATH,
                "query": ParameterLocation.QUERY,
                "header": ParameterLocation.HEADER,
                "cookie": ParameterLocation.COOKIE,
            }.get(loc_raw, ParameterLocation.QUERY)

        if is_v3:
            schema = _resolve_schema(raw.get("schema", {"type": "string"}), root)
        else:  # Swagger 2.0 inline typing
            schema = {"type": raw.get("type", "string")}
            if "enum" in raw:
                schema["enum"] = raw["enum"]
            if "items" in raw:
                schema["items"] = raw["items"]

        return Parameter(
            name=raw["name"],
            location=loc,
            required=bool(raw.get("required", loc == ParameterLocation.PATH)),
            description=raw.get("description"),
            schema=schema if isinstance(schema, dict) else {"type": "string"},
        )

    def _parse_request_body(
        self, request_body: dict[str, Any], root: dict[str, Any]
    ) -> dict[str, Any] | None:
        if "$ref" in request_body:
            request_body = _resolve_ref(request_body["$ref"], root)
        content = request_body.get("content", {})
        if not isinstance(content, dict):
            return None
        # Prefer JSON, otherwise take the first media type available.
        media = content.get("application/json") or next(iter(content.values()), None)
        if isinstance(media, dict) and "schema" in media:
            return _resolve_schema(media["schema"], root)
        return None

    def _parse_responses(
        self, responses: Any, root: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not isinstance(responses, dict):
            return None
        for code in ("200", "201", "2XX", "default"):
            if code in responses:
                resp = responses[code]
                if isinstance(resp, dict) and "$ref" in resp:
                    resp = _resolve_ref(resp["$ref"], root)
                if not isinstance(resp, dict):
                    continue
                # OpenAPI 3: content.<media>.schema; Swagger 2: schema.
                content = resp.get("content")
                if isinstance(content, dict):
                    media = content.get("application/json") or next(iter(content.values()), None)
                    if isinstance(media, dict) and "schema" in media:
                        return _resolve_schema(media["schema"], root)
                if "schema" in resp:
                    return _resolve_schema(resp["schema"], root)
        return None
