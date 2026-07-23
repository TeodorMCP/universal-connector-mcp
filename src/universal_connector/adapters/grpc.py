"""gRPC adapter (via server reflection).

Connects to a running gRPC server, uses reflection to enumerate services and
methods, and converts each method's request message descriptor into a JSON
schema so the agent knows what fields to send. Requires the server to have the
reflection service enabled.

Source format: ``grpc://host:port`` (insecure) or ``grpcs://host:port`` (TLS).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

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

_MAX_MSG_DEPTH = 4


def _channel(source: str):
    import grpc

    parts = urlsplit(source)
    target = parts.netloc or parts.path
    if not target:
        raise AdapterError("gRPC source must be grpc://host:port")
    if parts.scheme == "grpcs":
        return grpc.secure_channel(target, grpc.ssl_channel_credentials()), target
    return grpc.insecure_channel(target), target


def _field_schema(field, depth: int) -> dict[str, Any]:
    from google.protobuf.descriptor import FieldDescriptor

    ftype = field.type
    if ftype in (
        FieldDescriptor.TYPE_INT32,
        FieldDescriptor.TYPE_INT64,
        FieldDescriptor.TYPE_UINT32,
        FieldDescriptor.TYPE_UINT64,
        FieldDescriptor.TYPE_SINT32,
        FieldDescriptor.TYPE_SINT64,
        FieldDescriptor.TYPE_FIXED32,
        FieldDescriptor.TYPE_FIXED64,
    ):
        schema: dict[str, Any] = {"type": "integer"}
    elif ftype in (FieldDescriptor.TYPE_FLOAT, FieldDescriptor.TYPE_DOUBLE):
        schema = {"type": "number"}
    elif ftype == FieldDescriptor.TYPE_BOOL:
        schema = {"type": "boolean"}
    elif ftype == FieldDescriptor.TYPE_ENUM:
        values = [v.name for v in field.enum_type.values] if field.enum_type else []
        schema = {"type": "string", "enum": values}
    elif ftype == FieldDescriptor.TYPE_MESSAGE:
        schema = _message_schema(field.message_type, depth + 1)
    else:  # string, bytes
        schema = {"type": "string"}

    if field.label == FieldDescriptor.LABEL_REPEATED:
        return {"type": "array", "items": schema}
    return schema


def _message_schema(descriptor, depth: int = 0) -> dict[str, Any]:
    if descriptor is None or depth > _MAX_MSG_DEPTH:
        return {"type": "object"}
    properties: dict[str, Any] = {}
    for field in descriptor.fields:
        properties[field.name] = _field_schema(field, depth)
    return {"type": "object", "properties": properties}


class GrpcAdapter(SpecAdapter):
    protocol = Protocol.GRPC

    def parse(
        self,
        content: str,
        source: str,
        name: str,
        base_url: str | None = None,
    ) -> tuple[LoadedApi, list[Operation]]:
        try:
            from google.protobuf.descriptor_pool import DescriptorPool
            from grpc_reflection.v1alpha.proto_reflection_descriptor_database import (
                ProtoReflectionDescriptorDatabase,
            )
        except ImportError as exc:  # noqa: BLE001
            raise AdapterError(
                "gRPC support requires 'grpcio' and 'grpcio-reflection'. "
                "Install with: pip install 'universal-connector-mcp[grpc]'"
            ) from exc

        endpoint = base_url or source
        channel, target = _channel(source)
        try:
            db = ProtoReflectionDescriptorDatabase(channel)
            pool = DescriptorPool(db)
            service_names = [s for s in db.get_services() if "grpc.reflection" not in s]

            operations: list[Operation] = []
            for svc_name in service_names:
                svc_desc = pool.FindServiceByName(svc_name)
                for method in svc_desc.methods:
                    if method.client_streaming or method.server_streaming:
                        # Only unary-unary is supported for now.
                        continue
                    operations.append(
                        self._build_operation(
                            name=name,
                            endpoint=endpoint,
                            target=target,
                            service=svc_name,
                            method=method,
                        )
                    )
        finally:
            channel.close()

        host = urlsplit(source).hostname
        loaded = LoadedApi(
            name=name,
            protocol=Protocol.GRPC,
            base_url=endpoint,
            title=name,
            spec_source=source,
            hosts=[host.lower()] if host else [],
        )
        return loaded, operations

    def _build_operation(self, *, name, endpoint, target, service, method) -> Operation:
        input_schema = _message_schema(method.input_type)
        output_schema = _message_schema(method.output_type)
        default_auth = AuthScheme(type=AuthType.BEARER, scheme="bearer")
        return Operation(
            operation_id=f"{name}.{method.name}",
            api_name=name,
            protocol=Protocol.GRPC,
            method="RPC",
            path=f"/{service}/{method.name}",
            base_url=endpoint,
            summary=f"gRPC {service}.{method.name}",
            parameters=[
                Parameter(
                    name="body",
                    location=ParameterLocation.BODY,
                    required=True,
                    description=f"Request message for {method.name}",
                    schema=input_schema,
                )
            ],
            request_body_schema=input_schema,
            response_schema=output_schema,
            auth=[default_auth],
            extra={
                "target": target,
                "service": service,
                "method": method.name,
                "full_method": f"/{service}/{method.name}",
                "input_type": method.input_type.full_name,
                "output_type": method.output_type.full_name,
            },
        )
