const { NodeSDK } = require('@opentelemetry/sdk-node');
const { getNodeAutoInstrumentations } = require('@opentelemetry/auto-instrumentations-node');
const { PgInstrumentation } = require('@opentelemetry/instrumentation-pg');
const { Resource } = require('@opentelemetry/resources');
const { SemanticResourceAttributes } = require('@opentelemetry/semantic-conventions');
const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-http');
const { TraceIdRatioBasedSampler, ParentBasedSampler } = require('@opentelemetry/sdk-trace-base');

const serviceName = process.env.OTEL_SERVICE_NAME || 'payments-service';
const endpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT || 'http://tempo:4318';
const samplingRate = parseFloat(process.env.TRACE_SAMPLING_RATE || '1.0');

console.log(`Iniciando OpenTelemetry - Servicio: ${serviceName}`);

const traceExporter = new OTLPTraceExporter({ url: `${endpoint}/v1/traces` });

class IntelligentSampler {
  shouldSample(context, traceId, spanName, spanKind, attributes, links) {
    return new TraceIdRatioBasedSampler(samplingRate).shouldSample(context, traceId, spanName, spanKind, attributes, links);
  }
  toString() { return `IntelligentSampler{rate=${samplingRate}}`; }
}

const sdk = new NodeSDK({
  resource: new Resource({
    [SemanticResourceAttributes.SERVICE_NAME]: serviceName,
    [SemanticResourceAttributes.DEPLOYMENT_ENVIRONMENT]: process.env.NODE_ENV || 'development',
    ['service.version']: '1.0.0',
  }),
  traceExporter,
  sampler: new ParentBasedSampler({ root: new IntelligentSampler() }),
  instrumentations: [
    getNodeAutoInstrumentations({ '@opentelemetry/instrumentation-fs': { enabled: false } }),
    new PgInstrumentation({ enhancedDatabaseReporting: true }),
  ],
});

sdk.start();
console.log('OpenTelemetry iniciado correctamente');
process.on('SIGTERM', () => sdk.shutdown().then(() => process.exit(0)).catch(() => process.exit(1)));
