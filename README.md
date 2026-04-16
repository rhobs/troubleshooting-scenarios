# Troubleshooting Scenarios

Reproducible OpenShift scenarios for AI-assisted troubleshooting. Each scenario setups the environment environment and introduces a fault.

## Scenarios

| Scenario | Description |
|----------|-------------|
| [01-payments-api-failure](01-payments-api-failure/) | A routine rollout deploys a buggy version of the reporting service, which leaks database connections, exhausts a shared PostgreSQL pool, and causes payment failures in a separate namespace. |
