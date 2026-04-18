const jwt = require('jsonwebtoken');
const { trace } = require('@opentelemetry/api');
const logger = require('./logger');

// Configuración de autenticación
const JWT_SECRET = process.env.JWT_SECRET || 'default-secret-change-in-production';
const JWT_EXPIRATION = process.env.JWT_EXPIRATION || '24h';
const API_KEY = process.env.API_KEY || 'default-api-key-change-in-production';

/**
 * Genera un JWT token
 * @param {Object} payload - Datos a incluir en el token
 * @returns {string} JWT token
 */
function generateToken(payload = {}) {
  const defaultPayload = {
    iss: 'users-api-microservice',
    iat: Math.floor(Date.now() / 1000),
    type: 'api_access'
  };

  const tokenPayload = {
    ...defaultPayload,
    ...payload
  };

  return jwt.sign(tokenPayload, JWT_SECRET, {
    expiresIn: JWT_EXPIRATION
  });
}

/**
 * Verifica un JWT token
 * @param {string} token - Token a verificar
 * @returns {Object} Payload del token decodificado
 * @throws {Error} Si el token es inválido o ha expirado
 */
function verifyToken(token) {
  try {
    return jwt.verify(token, JWT_SECRET);
  } catch (error) {
    if (error.name === 'TokenExpiredError') {
      const err = new Error('Token has expired');
      err.name = 'TokenExpiredError';
      err.expiredAt = error.expiredAt;
      throw err;
    } else if (error.name === 'JsonWebTokenError') {
      const err = new Error('Invalid token');
      err.name = 'JsonWebTokenError';
      throw err;
    }
    throw error;
  }
}

/**
 * Middleware de autenticación JWT
 * Verifica que el request incluya un token válido en el header Authorization
 */
function authenticateToken(req, res, next) {
  const authHeader = req.headers['authorization'];
  const token = authHeader && authHeader.startsWith('Bearer ')
    ? authHeader.substring(7)
    : null;

  // Agregar contexto de autenticación al span
  const span = trace.getActiveSpan();
  if (span) {
    span.setAttribute('auth.method', 'jwt');
    span.setAttribute('auth.header_present', !!authHeader);
  }

  if (!token) {
    logger.warn('Authentication failed: No token provided', {
      requestId: req.id,
      correlationId: req.correlationId,
      endpoint: req.path,
      method: req.method
    });

    if (span) {
      span.setAttribute('auth.status', 'missing_token');
    }

    return res.status(401).json({
      status: 'ERROR',
      code: 401,
      message: 'Authentication required',
      error: 'No token provided',
      requestId: req.id
    });
  }

  try {
    const decoded = verifyToken(token);

    // Agregar información del token al request
    req.auth = {
      tokenPayload: decoded,
      authenticated: true
    };

    // Agregar contexto de autenticación al span
    if (span) {
      span.setAttribute('auth.status', 'authenticated');
      span.setAttribute('auth.token_type', decoded.type || 'unknown');
      if (decoded.client_id) {
        span.setAttribute('auth.client_id', decoded.client_id);
      }
    }

    logger.info('Authentication successful', {
      requestId: req.id,
      correlationId: req.correlationId,
      tokenType: decoded.type,
      clientId: decoded.client_id || 'unknown'
    });

    next();
  } catch (error) {
    logger.warn('Authentication failed: Invalid token', {
      requestId: req.id,
      correlationId: req.correlationId,
      error: error.message,
      errorType: error.name,
      endpoint: req.path,
      method: req.method
    });

    if (span) {
      span.setAttribute('auth.status', 'invalid_token');
      span.setAttribute('auth.error', error.name);
    }

    let statusCode = 401;
    let errorMessage = 'Invalid token';

    if (error.name === 'TokenExpiredError') {
      statusCode = 401;
      errorMessage = 'Token has expired';
    } else if (error.name === 'JsonWebTokenError') {
      statusCode = 401;
      errorMessage = 'Invalid token format';
    }

    return res.status(statusCode).json({
      status: 'ERROR',
      code: statusCode,
      message: 'Authentication failed',
      error: errorMessage,
      requestId: req.id
    });
  }
}

/**
 * Middleware de autenticación con API Key (alternativo)
 * Verifica que el request incluya una API key válida en el header x-api-key
 */
function authenticateApiKey(req, res, next) {
  const apiKey = req.headers['x-api-key'];

  // Agregar contexto de autenticación al span
  const span = trace.getActiveSpan();
  if (span) {
    span.setAttribute('auth.method', 'api_key');
    span.setAttribute('auth.header_present', !!apiKey);
  }

  if (!apiKey) {
    logger.warn('Authentication failed: No API key provided', {
      requestId: req.id,
      correlationId: req.correlationId,
      endpoint: req.path,
      method: req.method
    });

    if (span) {
      span.setAttribute('auth.status', 'missing_api_key');
    }

    return res.status(401).json({
      status: 'ERROR',
      code: 401,
      message: 'Authentication required',
      error: 'No API key provided',
      requestId: req.id
    });
  }

  if (apiKey !== API_KEY) {
    logger.warn('Authentication failed: Invalid API key', {
      requestId: req.id,
      correlationId: req.correlationId,
      endpoint: req.path,
      method: req.method
    });

    if (span) {
      span.setAttribute('auth.status', 'invalid_api_key');
    }

    return res.status(401).json({
      status: 'ERROR',
      code: 401,
      message: 'Authentication failed',
      error: 'Invalid API key',
      requestId: req.id
    });
  }

  // Autenticación exitosa
  req.auth = {
    method: 'api_key',
    authenticated: true
  };

  if (span) {
    span.setAttribute('auth.status', 'authenticated');
  }

  logger.info('Authentication successful (API Key)', {
    requestId: req.id,
    correlationId: req.correlationId
  });

  next();
}

/**
 * Middleware de autenticación flexible
 * Acepta tanto JWT como API Key
 */
function authenticate(req, res, next) {
  const authHeader = req.headers['authorization'];
  const apiKey = req.headers['x-api-key'];

  // Prioridad: JWT > API Key
  if (authHeader && authHeader.startsWith('Bearer ')) {
    return authenticateToken(req, res, next);
  } else if (apiKey) {
    return authenticateApiKey(req, res, next);
  } else {
    logger.warn('Authentication failed: No credentials provided', {
      requestId: req.id,
      correlationId: req.correlationId,
      endpoint: req.path,
      method: req.method
    });

    const span = trace.getActiveSpan();
    if (span) {
      span.setAttribute('auth.status', 'no_credentials');
    }

    return res.status(401).json({
      status: 'ERROR',
      code: 401,
      message: 'Authentication required',
      error: 'No authentication credentials provided',
      hint: 'Include either "Authorization: Bearer <token>" or "x-api-key: <key>" header',
      requestId: req.id
    });
  }
}

module.exports = {
  generateToken,
  verifyToken,
  authenticateToken,
  authenticateApiKey,
  authenticate,
  JWT_SECRET,
  JWT_EXPIRATION,
  API_KEY
};
