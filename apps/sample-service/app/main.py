from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from opentelemetry import metrics, trace


def _otel_disabled() -> bool:
    return os.getenv("DISABLE_OTEL", "").lower() in ("1", "true", "yes")


def configure_telemetry() -> None:
    """Heavy OTLP / protobuf imports are lazy so local tests (e.g. Python 3.14) can run with DISABLE_OTEL."""
    if _otel_disabled():
        logging.basicConfig(level=logging.INFO)
        return

    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {
            "service.name": "aiops-sample-service",
            "service.version": "0.1.0",
            "deployment.environment": "local",
        }
    )

    trace_exporter = OTLPSpanExporter()
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
    trace.set_tracer_provider(tracer_provider)

    metric_exporter = OTLPMetricExporter()
    reader = PeriodicExportingMetricReader(
        metric_exporter,
        export_interval_millis=5_000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)

    logging.basicConfig(level=logging.INFO)
    LoggingInstrumentor().instrument(set_logging_format=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_telemetry()
    meter = metrics.get_meter(__name__)
    app.state.work_counter = meter.create_counter(
        "sample_service.work_requests",
        unit="1",
        description="Count of /work requests",
    )
    if not _otel_disabled():
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    yield


app = FastAPI(title="aiops-sample-service", lifespan=lifespan)
logger = logging.getLogger(__name__)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/work")
async def work(request: Request) -> dict[str, str]:
    request.app.state.work_counter.add(1, {"route": "/work"})
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("work.do_fake_task"):
        time.sleep(0.05)
        logger.info("finished fake work")
    return {"status": "done"}
