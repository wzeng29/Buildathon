// Configuración de OpenTelemetry para Grafana Stack (Tempo)
const { NodeSDK } = require('@opentelemetry/sdk-node');
const { getNodeAutoInstrumentations } = require('@opentelemetry/auto-instrumentations-node');
const { PgInstrumentation } = require('@opentelemetry/instrumentation-pg');
const { Resource } = require('@opentelemetry/resources');
const { SemanticResourceAttributes } = require('@opentelemetry/semantic-conventions');
const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-http');
const { TraceIdRatioBasedSampler, ParentBasedSampler, AlwaysOnSampler } = require('@opentelemetry/sdk-trace-base');

const serviceName = process.env.OTEL_SERVICE_NAME || 'users-api-microservice';
const endpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT || 'http://tempo:4318';

// Configuración de sampling inteligente
// Sampling rate desde variable de entorno (default: 1.0 = 100% para desarrollo)
const samplingRate = parseFloat(process.env.TRACE_SAMPLING_RATE || '1.0');

console.log('🚀 Iniciando OpenTelemetry...');
console.log(`   📦 Servicio: ${serviceName}`);
console.log(`   🎯 Endpoint: ${endpoint}`);
console.log(`   🎲 Sampling Rate: ${samplingRate * 100}%`);

const traceExporter = new OTLPTraceExporter({
  url: `${endpoint}/v1/traces`,
});

// Sampler personalizado: mantiene errores y traces lentos, samplea el resto
class IntelligentSampler {
  shouldSample(context, traceId, spanName, spanKind, attributes, links) {
    // SIEMPRE samplear si hay indicadores de error o latencia alta
    // Nota: Los atributos se setean después, así que usamos un sampler parent-based
    // que permite que los spans hijos hereden la decisión del parent

    // Para producción real, implementarías lógica basada en:
    // - attributes['http.status_code'] >= 500 -> AlwaysOn
    // - attributes['http.request.duration'] > 1000 -> AlwaysOn
    // - attributes['error'] === true -> AlwaysOn

    // Por ahora, usamos TraceIdRatioBasedSampler con rate configurable
    const ratioSampler = new TraceIdRatioBasedSampler(samplingRate);
    return ratioSampler.shouldSample(context, traceId, spanName, spanKind, attributes, links);
  }

  toString() {
    return `IntelligentSampler{rate=${samplingRate}}`;
  }
}

// Usar ParentBasedSampler para que los spans hijos respeten la decisión del parent
const sampler = new ParentBasedSampler({
  root: new IntelligentSampler(),
});

const sdk = new NodeSDK({
  resource: new Resource({
    [SemanticResourceAttributes.SERVICE_NAME]: serviceName,
    // Agregar atributos de deployment environment
    [SemanticResourceAttributes.DEPLOYMENT_ENVIRONMENT]: process.env.NODE_ENV || 'development',
    ['service.version']: process.env.SERVICE_VERSION || '1.0.0',
  }),
  traceExporter: traceExporter,
  sampler: sampler,
  instrumentations: [
    getNodeAutoInstrumentations({
      '@opentelemetry/instrumentation-fs': {
        enabled: false,
      },
      // Configuración avanzada de HTTP instrumentation
      '@opentelemetry/instrumentation-http': {
        // Hook para decidir sampling basado en response
        responseHook: (span, response) => {
          // Marcar el span si hay error para forzar sampling en implementaciones futuras
          if (response.statusCode >= 500) {
            span.setAttribute('force.sampling', true);
            span.setAttribute('sampling.priority', 1);
          }
        },
      },
    }),
    // Instrumentación explícita de PostgreSQL para capturar métricas de DB
    new PgInstrumentation({
      // Capturar parámetros de query (útil para debugging, cuidado en producción con datos sensibles)
      enhancedDatabaseReporting: true,
      // Hook para agregar información adicional a los spans de DB
      responseHook: (span, responseInfo) => {
        // Agregar información sobre el número de filas devueltas
        if (responseInfo.data && responseInfo.data.rowCount !== undefined) {
          span.setAttribute('db.pg.rows', responseInfo.data.rowCount);
        }
      },
    }),
  ],
});

sdk.start();
console.log('✅ OpenTelemetry iniciado correctamente');

process.on('SIGTERM', () => {
  sdk.shutdown()
    .then(() => console.log('📴 OpenTelemetry detenido'))
    .catch((err) => console.error('❌ Error:', err))
    .finally(() => process.exit(0));
});
