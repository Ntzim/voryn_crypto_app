/**
 * Voryn on Railway (Infrastructure as Code). See docs/DEPLOY.md.
 *
 *   railway login && railway link      # once, in this repository
 *   railway config plan                # review
 *   railway config apply               # create/update services
 *
 * Secrets are not in this file: create them as *shared variables* in the Railway
 * environment first (SECRET_KEY, ENCRYPTION_KEYS, FRONTEND_URL, EMAIL_FROM, RESEND_API_KEY).
 * Optional keys (ANTHROPIC_API_KEY, COINGECKO_API_KEY, SENTRY_DSN) are kept as set in the
 * dashboard on each service that uses them.
 */
import { defineRailway, github, postgres, preserve, redis, service } from "railway/iac";

const REPO = "Ntzim/voryn_crypto_app";
const BRANCH = "main";
/** The API listens on this port on the private network; the web BFF calls it there. */
const API_PORT = "8000";

export default defineRailway((ctx, project) => {
  const db = postgres("postgres");
  const cache = redis("redis");

  const backend = (watch: string[]) => ({
    source: github(REPO, { branch: BRANCH, rootDirectory: "backend" }),
    build: { builder: "DOCKERFILE" as const, watchPatterns: watch },
  });

  // Every backend process reads the same configuration (the worker decrypts exchange keys
  // and signs tokens too, so the secrets must match the API's).
  const common = {
    ENVIRONMENT: "production",
    DATABASE_URL: db.env.DATABASE_URL,
    REDIS_URL: cache.env.REDIS_URL,
    SECRET_KEY: ctx.shared.SECRET_KEY,
    ENCRYPTION_KEYS: ctx.shared.ENCRYPTION_KEYS,
    FRONTEND_URL: ctx.shared.FRONTEND_URL,
    EMAIL_BACKEND: "resend",
    EMAIL_FROM: ctx.shared.EMAIL_FROM,
    RESEND_API_KEY: ctx.shared.RESEND_API_KEY,
    TRUST_PROXY_HEADERS: "true",
    COINGECKO_API_KEY: preserve(),
    SENTRY_DSN: preserve(),
  };

  const api = service("api", {
    ...backend(["/backend/**"]),
    // Runs once per deploy, before traffic moves; a failure stops the deploy.
    preDeploy: "alembic upgrade head",
    healthcheck: "/health/ready",
    healthcheckTimeout: 120,
    deploy: { restartPolicyType: "ON_FAILURE", restartPolicyMaxRetries: 10 },
    // No public domain: only the web BFF reaches the API, over the private network.
    env: { ...common, PORT: API_PORT, HOST: "::", ANTHROPIC_API_KEY: preserve() },
  });

  const worker = service("worker", {
    ...backend(["/backend/**"]),
    start: "celery -A app.worker.celery_app worker --loglevel=INFO --concurrency=2 -Q voryn",
    deploy: { restartPolicyType: "ALWAYS" },
    env: common,
  });

  // Exactly one scheduler, or periodic jobs would run twice.
  const beat = service("beat", {
    ...backend(["/backend/app/worker.py", "/backend/app/core/**", "/backend/pyproject.toml"]),
    start: "celery -A app.worker.celery_app beat --loglevel=INFO --schedule=/tmp/celerybeat-schedule",
    replicas: 1,
    deploy: { restartPolicyType: "ALWAYS" },
    env: common,
  });

  const web = service("web", {
    source: github(REPO, { branch: BRANCH, rootDirectory: "frontend" }),
    build: { builder: "DOCKERFILE", watchPatterns: ["/frontend/**"] },
    healthcheck: "/entrar",
    healthcheckTimeout: 60,
    deploy: { restartPolicyType: "ON_FAILURE", restartPolicyMaxRetries: 10 },
    env: {
      API_PRIVATE_HOST: api.env.RAILWAY_PRIVATE_DOMAIN,
      API_PRIVATE_PORT: API_PORT,
      // The Railway edge overwrites X-Real-IP; the BFF rebuilds X-Forwarded-For from it.
      CLIENT_IP_HEADER: "x-real-ip",
    },
  });

  return project("voryn", { resources: [db, cache, api, worker, beat, web] });
});
