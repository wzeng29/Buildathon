const { trace } = require('@opentelemetry/api');

// Niveles de log
const LogLevel = {
  DEBUG: 0,
  INFO: 1,
  WARN: 2,
  ERROR: 3,
  FATAL: 4
};

// Configuración del logger
const config = {
  minLevel: process.env.LOG_LEVEL ? LogLevel[process.env.LOG_LEVEL.toUpperCase()] : LogLevel.INFO,
  enableColors: process.env.NODE_ENV !== 'production'
};

class Logger {
  constructor(context = {}) {
    this.context = context;
  }

  // Crear logger hijo con contexto adicional
  child(additionalContext) {
    return new Logger({ ...this.context, ...additionalContext });
  }

  // Método privado para escribir logs
  _log(level, message, data = {}) {
    const levelValue = LogLevel[level];

    // Filtrar por nivel mínimo
    if (levelValue < config.minLevel) {
      return;
    }

    // Obtener contexto de tracing
    const span = trace.getActiveSpan();
    const spanContext = span?.spanContext();

    const logEntry = {
      level: level.toLowerCase(),
      timestamp: new Date().toISOString(),
      message,
      ...this.context,
      ...data,
      traceId: spanContext?.traceId || 'unknown',
      spanId: spanContext?.spanId || 'unknown'
    };

    // Escribir a stdout/stderr según nivel
    const output = levelValue >= LogLevel.ERROR ? console.error : console.log;
    output(JSON.stringify(logEntry));
  }

  debug(message, data) {
    this._log('DEBUG', message, data);
  }

  info(message, data) {
    this._log('INFO', message, data);
  }

  warn(message, data) {
    this._log('WARN', message, data);
  }

  error(message, data) {
    this._log('ERROR', message, data);
  }

  fatal(message, data) {
    this._log('FATAL', message, data);
  }

  // Método helper para loggear requests HTTP
  logRequest(req, res, duration) {
    const logData = {
      method: req.method,
      path: req.path,
      route: req.route ? req.route.path : req.path,
      statusCode: res.statusCode,
      duration: `${duration}ms`,
      ip: req.ip,
      userAgent: req.get('user-agent') || 'unknown',
      requestId: req.id,
      correlationId: req.correlationId
    };

    if (res.statusCode >= 500) {
      this.error('HTTP request failed', logData);
    } else if (res.statusCode >= 400) {
      this.warn('HTTP request client error', logData);
    } else {
      this.info('HTTP request', logData);
    }
  }
}

// Exportar instancia global
module.exports = new Logger();
module.exports.Logger = Logger;
module.exports.LogLevel = LogLevel;
