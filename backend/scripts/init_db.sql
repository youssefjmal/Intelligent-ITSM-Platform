-- Bootstrap database for the Jira ticket backend.
CREATE DATABASE jira_tickets;
\connect jira_tickets
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
