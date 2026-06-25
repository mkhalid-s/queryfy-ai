# QueryfyAI - Getting Started Guide

A comprehensive onboarding guide for developers and users to set up, configure, and use QueryfyAI.

---

## Table of Contents

1. [Introduction](#introduction)
2. [Prerequisites](#prerequisites)
3. [Quick Start (5 Minutes)](#quick-start-5-minutes)
4. [Developer Setup](#developer-setup)
   - [Backend Setup](#backend-setup)
   - [Frontend Setup](#frontend-setup)
   - [Running Both Together](#running-both-together)
5. [Database Migrations (Alembic)](#database-migrations-alembic)
6. [LLM Provider Configuration](#llm-provider-configuration)
   - [OpenAI](#openai)
   - [Anthropic (Claude)](#anthropic-claude)
   - [Azure OpenAI](#azure-openai)
   - [AWS Bedrock](#aws-bedrock)
   - [Google Vertex AI / Gemini](#google-vertex-ai--gemini)
   - [Groq](#groq)
   - [Ollama (Local LLMs)](#ollama-local-llms)
   - [Other Providers](#other-providers)
   - [OAuth Gateway (Enterprise)](#oauth-gateway-enterprise)
   - [Custom Endpoint](#custom-endpoint)
6. [Database Configuration](#database-configuration)
   - [PostgreSQL](#postgresql)
   - [MySQL](#mysql)
   - [SQL Server](#sql-server)
   - [Oracle](#oracle)
   - [Snowflake](#snowflake)
   - [BigQuery](#bigquery)
   - [MongoDB](#mongodb)
   - [Cassandra](#cassandra)
   - [DynamoDB](#dynamodb)
   - [DuckDB](#duckdb)
   - [SQLite](#sqlite)
7. [Context Studio](#context-studio)
8. [Vector Database Setup](#vector-database-setup)
   - [ChromaDB (Default)](#chromadb-default)
   - [Qdrant](#qdrant)
9. [Loading Sample Data](#loading-sample-data)
10. [Using the Application](#using-the-application)
11. [Production Deployment](#production-deployment)
12. [Common Commands Reference](#common-commands-reference)
13. [Troubleshooting Quick Reference](#troubleshooting-quick-reference)

---

## Introduction

### What is QueryfyAI?

QueryfyAI is a **Natural Language to SQL** application that allows you to query your databases using plain English. Instead of writing complex SQL queries, you can simply ask questions like:

- "Show me the top 10 customers by revenue"
- "What were the total sales last month?"
- "List all products with stock below 100"

QueryfyAI will:
1. Understand your question
2. Analyze your database schema
3. Generate the appropriate SQL query
4. Execute it (optionally) and show you the results
5. Visualize results with auto-detected charts

### Key Features

- **Multi-Database Support**: PostgreSQL, MySQL, SQL Server, Oracle, Snowflake, BigQuery, MongoDB, Cassandra, DynamoDB, DuckDB, SQLite
- **15+ LLM Providers**: OpenAI, Anthropic Claude, Azure OpenAI, AWS Bedrock, Google Vertex AI, Gemini, Groq, Ollama, Together AI, Mistral, Cohere, DeepSeek, Replicate, and corporate OAuth gateways
- **Smart Visualizations**: Automatic chart type detection (bar, line, pie, scatter, area) based on your data
- **Query History**: Track and replay past queries
- **Security-First**: Read-only queries, prompt injection protection, SQL validation
- **Export**: Download results as Excel spreadsheets
- **Intelligent Query Generation**: Few-shot learning, Chain-of-Thought reasoning, self-correction for improved accuracy

---

## Prerequisites

Before you begin, make sure you have the following installed on your computer.

### Required Software

#### 1. Python 3.11 or Higher

Python is needed to run the backend server.

**Check if installed:**
```bash
python --version
# or
python3 --version
```

You should see `Python 3.11.x` or higher.

**Installation:**

| Platform | Instructions |
|----------|-------------|
| **Windows** | Download from [python.org](https://www.python.org/downloads/). During installation, check "Add Python to PATH" |
| **macOS** | `brew install python@3.11` (requires [Homebrew](https://brew.sh)) or download from [python.org](https://www.python.org/downloads/) |
| **Linux (Ubuntu/Debian)** | `sudo apt update && sudo apt install python3.11 python3.11-venv python3-pip` |
| **Linux (Fedora)** | `sudo dnf install python3.11` |

#### 2. Node.js 20 or Higher

Node.js is needed to run the frontend development server.

**Check if installed:**
```bash
node --version
```

You should see `v20.x.x` or higher.

**Installation:**

| Platform | Instructions |
|----------|-------------|
| **All Platforms (Recommended)** | Use [nvm](https://github.com/nvm-sh/nvm) (Node Version Manager):<br>`curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh \| bash`<br>Then: `nvm install 20` |
| **Windows** | Download from [nodejs.org](https://nodejs.org/) or use [nvm-windows](https://github.com/coreybutler/nvm-windows) |
| **macOS** | `brew install node@20` |
| **Linux** | See [NodeSource distributions](https://github.com/nodesource/distributions) |

#### 3. Git

Git is needed to clone the repository.

**Check if installed:**
```bash
git --version
```

**Installation:**

| Platform | Instructions |
|----------|-------------|
| **Windows** | Download from [git-scm.com](https://git-scm.com/download/win) |
| **macOS** | `xcode-select --install` or `brew install git` |
| **Linux** | `sudo apt install git` (Ubuntu) or `sudo dnf install git` (Fedora) |

### Optional Software

#### 4. Docker (For Production Deployment)

Docker is only needed if you plan to deploy QueryfyAI in production.

**Installation:** Download [Docker Desktop](https://www.docker.com/products/docker-desktop/) for Windows/macOS, or install [Docker Engine](https://docs.docker.com/engine/install/) for Linux.

#### 5. Redis (For Session Persistence)

Redis enables session persistence across server restarts. Without Redis, the application falls back to in-memory storage (sessions are lost when the server restarts).

**Installation (optional for development):**
```bash
# macOS
brew install redis && brew services start redis

# Ubuntu/Debian
sudo apt install redis-server && sudo systemctl start redis

# Windows
# Use Docker: docker run -d -p 6379:6379 redis

# Or use Windows Subsystem for Linux (WSL)
```

### What is a Terminal?

Throughout this guide, you'll need to run commands in a **terminal** (also called command prompt or shell):

| Platform | How to Open |
|----------|-------------|
| **Windows** | Press `Win + R`, type `cmd` or `powershell`, press Enter. Or search for "Terminal" in the Start menu |
| **macOS** | Press `Cmd + Space`, type "Terminal", press Enter |
| **Linux** | Press `Ctrl + Alt + T` or search for "Terminal" in applications |

---

## Quick Start (5 Minutes)

For experienced developers who want to get up and running quickly:

```bash
# 1. Clone the repository
git clone https://github.com/mkhalid-s/queryfy-ai.git
cd nl2sql-app

# 2. Backend setup
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your LLM provider settings (see LLM Provider Configuration section)
uvicorn app.main:app --reload --port 8000

# 3. Frontend setup (in a new terminal)
cd frontend
npm install
npm run dev

# 4. Open http://localhost:5173 in your browser
```

### Try Analyst Mode

To experience QueryfyAI's AI Data Analyst capabilities with insight-rich responses:

**In the UI:**
1. Open the application at `http://localhost:5173`
2. Complete the setup wizard (LLM provider + database connection)
3. Toggle **"Analyst Mode"** in the query input options
4. Ask a question: "Show me top 10 customers by revenue"
5. Watch the agent work in real-time:
   - Searching for relevant tables
   - Generating optimized SQL
   - Executing and analyzing results
   - Detecting insights and patterns
   - Recommending chart types

**What you'll get:**
- ✅ Generated SQL query
- ✅ Executed results (sample + row count)
- ✅ Key findings (e.g., "Top 3 customers account for 45% of revenue")
- ✅ Confidence score (0.0-1.0)
- ✅ Auto-generated chart with recommended type
- ✅ Data quality assessment (completeness, issues detected)

**Using the API:**
```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "your-session-id",
    "message": "Show me top 10 customers by revenue",
    "mode": "analyst",
    "stream": true,
    "include_chart": true
  }'
```

**Multi-Turn Conversations:**
```bash
# First question
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "your-session-id",
    "message": "Show me Q4 sales by region",
    "mode": "analyst"
  }'

# Follow-up question (uses previous context)
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "your-session-id",
    "message": "Now filter those by revenue > 100K",
    "mode": "analyst",
    "continue_conversation": true
  }'
```

For detailed step-by-step instructions, continue reading below.

---

## Developer Setup

This section provides detailed instructions for setting up your local development environment.

### Backend Setup

The backend is a Python application using FastAPI. Follow these steps:

#### Step 1: Clone the Repository

Open your terminal and run:

```bash
git clone https://github.com/mkhalid-s/queryfy-ai.git
cd nl2sql-app
```

This downloads the project files to your computer and enters the project directory.

#### Step 2: Navigate to the Backend Directory

```bash
cd backend
```

#### Step 3: Create a Python Virtual Environment

A virtual environment keeps the project's dependencies separate from other Python projects on your computer.

```bash
python -m venv venv
```

This creates a folder called `venv` containing an isolated Python installation.

#### Step 4: Activate the Virtual Environment

**macOS/Linux:**
```bash
source venv/bin/activate
```

**Windows (Command Prompt):**
```cmd
venv\Scripts\activate.bat
```

**Windows (PowerShell):**
```powershell
venv\Scripts\Activate.ps1
```

After activation, you should see `(venv)` at the beginning of your terminal prompt:
```
(venv) user@computer:~/nl2sql-app/backend$
```

#### Step 5: Install Dependencies

```bash
pip install -r requirements.txt
```

This installs all the Python packages needed by the backend. It may take a few minutes.

#### Step 6: Create Your Environment File

```bash
cp .env.example .env
```

This creates a copy of the example configuration file. You'll edit this file to add your settings.

#### Step 7: Configure Environment Variables

Open the `.env` file in a text editor. At minimum, you need to configure an LLM provider. Here's a simple setup using OpenAI:

```bash
# Open with your preferred editor
# macOS/Linux:
nano .env
# or
code .env  # if you have VS Code

# Windows:
notepad .env
```

Find and update these lines:

```env
# Change the provider to openai
DEFAULT_LLM_PROVIDER=openai

# Add your OpenAI API key (get one from https://platform.openai.com/api-keys)
DEFAULT_LLM_API_KEY=replace_with_openai_api_key-here

# Set the model
DEFAULT_LLM_MODEL=gpt-4
```

Save the file. See the [LLM Provider Configuration](#llm-provider-configuration) section for other providers.

#### Advanced Configuration (Optional)

For advanced users, here are additional configuration options:

**SQL Agent Configuration:**
```env
# Self-correction retries (1-5, default: 3)
AGENT_MAX_RETRIES=3

# Use PostgreSQL for agent state persistence
AGENT_USE_POSTGRES_STATE=true

# Agent execution timeout in seconds
AGENT_TIMEOUT_SECONDS=120
```

**Vector Database Configuration:**
```env
# Vector DB type: chromadb (default) or qdrant
VECTOR_DB_TYPE=chromadb

# Embedding provider: local (default), openai
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=all-MiniLM-L6-v2
```

**OpenTelemetry Tracing:**
```env
# Enable distributed tracing
OTEL_ENABLED=true
OTEL_SERVICE_NAME=queryfyai-backend
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317

# Sampling: 1.0 = all traces, 0.1 = 10%
OTEL_TRACES_SAMPLER_ARG=1.0
```

#### Step 8: Run the Development Server

```bash
uvicorn app.main:app --reload --port 8000
```

You should see output like:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [12345]
INFO:     Started server process [12346]
INFO:     Application startup complete.
```

#### Step 9: Verify the Backend is Running

Open a new terminal (keep the server running in the first one) and run:

```bash
curl http://localhost:8000/health
```

**Windows (without curl):** Open `http://localhost:8000/health` in your browser.

You should see a JSON response like:
```json
{
  "status": "healthy",
  "version": "1.2.0",
  ...
}
```

The backend is now running. Keep this terminal open.

---

### Frontend Setup

The frontend is a Vue.js application. Open a **new terminal** for these steps.

#### Step 1: Navigate to the Frontend Directory

From the project root:
```bash
cd frontend
```

Or if you're still in the backend directory:
```bash
cd ../frontend
```

#### Step 2: Install Dependencies

```bash
npm install
```

This downloads all the JavaScript packages needed by the frontend. It may take a few minutes.

#### Step 3: Run the Development Server

```bash
npm run dev
```

You should see output like:
```
  VITE v5.0.12  ready in 500 ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: http://192.168.1.100:5173/
  ➜  press h + enter to show help
```

#### Step 4: Access the Application

Open your web browser and go to:
```
http://localhost:5173
```

You should see the QueryfyAI interface.

---

### Running Both Together

For development, you need both the backend and frontend running simultaneously.

#### Option 1: Two Terminal Windows

1. **Terminal 1 (Backend)**:
   ```bash
   cd backend
   source venv/bin/activate  # Windows: venv\Scripts\activate
   uvicorn app.main:app --reload --port 8000
   ```

2. **Terminal 2 (Frontend)**:
   ```bash
   cd frontend
   npm run dev
   ```

#### Option 2: VS Code Tasks (Recommended for VS Code Users)

Create `.vscode/tasks.json` in the project root:

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Backend",
      "type": "shell",
      "command": "source venv/bin/activate && uvicorn app.main:app --reload --port 8000",
      "options": { "cwd": "${workspaceFolder}/backend" },
      "isBackground": true,
      "problemMatcher": []
    },
    {
      "label": "Frontend",
      "type": "shell",
      "command": "npm run dev",
      "options": { "cwd": "${workspaceFolder}/frontend" },
      "isBackground": true,
      "problemMatcher": []
    },
    {
      "label": "Start All",
      "dependsOn": ["Backend", "Frontend"],
      "problemMatcher": []
    }
  ]
}
```

Then press `Ctrl+Shift+P` (or `Cmd+Shift+P` on Mac), type "Run Task", select "Start All".

#### Option 3: Using a Process Manager

Install `concurrently`:
```bash
npm install -g concurrently
```

Run from project root:
```bash
concurrently "cd backend && source venv/bin/activate && uvicorn app.main:app --reload" "cd frontend && npm run dev"
```

---

## Database Migrations (Alembic)

QueryfyAI uses Alembic for database schema migrations. This is required when using PostgreSQL for state persistence (Context Studio data, agent state, etc.).

### When Are Migrations Needed?

- **Required**: When `DATABASE_URL` is configured (PostgreSQL for state)
- **Not Required**: When using only in-memory session storage

### Initial Setup

```bash
cd backend

# 1. Ensure DATABASE_URL is set in .env
# Example: DATABASE_URL=postgresql://queryfyai:password@localhost:5432/queryfyai

# 2. Create the database (PostgreSQL)
createdb queryfyai

# 3. Apply all migrations
alembic upgrade head
```

### Common Alembic Commands

| Command | Description |
|---------|-------------|
| `alembic upgrade head` | Apply all pending migrations |
| `alembic current` | Show current migration version |
| `alembic history` | View migration history |
| `alembic downgrade -1` | Rollback one migration |
| `alembic downgrade base` | Rollback all migrations |
| `alembic revision --autogenerate -m "desc"` | Create new migration (auto-detect) |
| `alembic revision -m "desc"` | Create empty migration |

### Creating a New Migration

When you modify SQLAlchemy models in `app/models/db_models.py`:

```bash
# 1. Make your model changes
# 2. Generate migration
alembic revision --autogenerate -m "add user preferences table"

# 3. Review the generated migration file in alembic/versions/
# 4. Apply the migration
alembic upgrade head
```

### Docker/Production

Migrations run automatically on container startup. For manual execution:

```bash
# Docker Compose
docker exec -it queryfyai-backend alembic upgrade head

# Kubernetes
kubectl exec -it deploy/queryfyai-backend -- alembic upgrade head

# Check current version
docker exec -it queryfyai-backend alembic current
```

### Troubleshooting Migrations

| Issue | Solution |
|-------|----------|
| "Can't locate revision" | Run `alembic stamp head` to sync state |
| "Target database is not up to date" | Run `alembic upgrade head` |
| "No changes detected" | Ensure models are imported in `alembic/env.py` |
| Connection refused | Check DATABASE_URL and database availability |

---

## LLM Provider Configuration

QueryfyAI supports multiple LLM (Large Language Model) providers. You can configure a default provider in your `.env` file or select a provider in the application's settings.

### OpenAI

OpenAI provides GPT-4 and GPT-3.5 models.

#### Getting an API Key

1. Go to [OpenAI Platform](https://platform.openai.com/)
2. Sign up or log in
3. Navigate to [API Keys](https://platform.openai.com/api-keys)
4. Click "Create new secret key"
5. Copy the key (you won't be able to see it again)

#### Configuration

**Option A: Environment Variable (Recommended for Development)**

In your `backend/.env` file:
```env
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_API_KEY=sk-your-api-key-here
DEFAULT_LLM_MODEL=gpt-4
```

**Option B: In the Application UI**

1. Click the **Settings** button (gear icon)
2. In the LLM Configuration section, select "OpenAI"
3. Enter your API key
4. Select your model
5. Click "Test Connection" to verify

#### Model Options

| Model | Description | Cost |
|-------|-------------|------|
| `gpt-4` | Most capable, best for complex queries | Higher |
| `gpt-4-turbo` | Faster GPT-4 with 128K context | Medium-High |
| `gpt-3.5-turbo` | Fast and cost-effective | Lower |

#### Example Configuration (UI)
```json
{
  "provider": "openai",
  "api_key": "sk-...",
  "model": "gpt-4"
}
```

---

### Anthropic (Claude)

Anthropic provides Claude models, known for their strong reasoning capabilities.

#### Getting an API Key

1. Go to [Anthropic Console](https://console.anthropic.com/)
2. Sign up or log in
3. Navigate to [API Keys](https://console.anthropic.com/settings/keys)
4. Click "Create Key"
5. Copy the key

#### Configuration

**Environment Variable:**
```env
DEFAULT_LLM_PROVIDER=anthropic
DEFAULT_LLM_API_KEY=replace_with_anthropic_api_key
DEFAULT_LLM_MODEL=claude-sonnet-4-20250514
```

**In the Application UI:**
```json
{
  "provider": "anthropic",
  "api_key": "sk-ant-...",
  "model": "claude-sonnet-4-20250514"
}
```

#### Model Options

| Model | Description | Cost |
|-------|-------------|------|
| `claude-sonnet-4-20250514` | Best balance of capability and speed | Medium |
| `claude-3-5-sonnet-20241022` | Previous generation, still excellent | Medium |
| `claude-3-haiku-20240307` | Fastest, most cost-effective | Lower |

---

### Azure OpenAI

For organizations using Microsoft Azure's OpenAI Service.

#### Prerequisites

1. Azure subscription with OpenAI Service enabled
2. Deployed model in Azure OpenAI Studio

#### Getting Your Credentials

1. Go to [Azure Portal](https://portal.azure.com/)
2. Navigate to your Azure OpenAI resource
3. Find **Keys and Endpoint** in the left menu
4. Copy **Key 1** and **Endpoint**
5. In Azure OpenAI Studio, note your **Deployment Name**

#### Configuration

**Environment Variable:**
```env
DEFAULT_LLM_PROVIDER=azure
DEFAULT_LLM_BASE_URL=https://your-resource-name.openai.azure.com
DEFAULT_LLM_API_KEY=your-azure-api-key
DEFAULT_LLM_MODEL=your-deployment-name
```

**In the Application UI:**
```json
{
  "provider": "azure",
  "base_url": "https://your-resource-name.openai.azure.com",
  "api_key": "your-azure-api-key",
  "model": "your-deployment-name"
}
```

**Note:** The `model` field should be your **deployment name**, not the model name (e.g., `my-gpt4-deployment`, not `gpt-4`).

---

### AWS Bedrock

For organizations using AWS Bedrock for model access.

#### Prerequisites

1. AWS account with Bedrock enabled
2. IAM credentials with Bedrock permissions
3. Model access granted in Bedrock console

#### Configuration

**Environment Variable:**
```env
DEFAULT_LLM_PROVIDER=bedrock
DEFAULT_LLM_MODEL=anthropic.claude-3-sonnet-20240229-v1:0
DEFAULT_LLM_BASE_URL=us-east-1
# AWS credentials via environment or IAM role
```

**In the Application UI:**
```json
{
  "provider": "bedrock",
  "model": "anthropic.claude-3-sonnet-20240229-v1:0",
  "base_url": "us-east-1"
}
```

#### Model Options

| Model | Description |
|-------|-------------|
| `anthropic.claude-3-sonnet-20240229-v1:0` | Claude 3 Sonnet |
| `anthropic.claude-3-haiku-20240307-v1:0` | Claude 3 Haiku (faster) |
| `amazon.titan-text-express-v1` | Amazon Titan |

---

### Google Vertex AI / Gemini

Google Cloud's AI platform and direct Gemini API.

#### Vertex AI Configuration

**Environment Variable:**
```env
DEFAULT_LLM_PROVIDER=vertex_ai
DEFAULT_LLM_MODEL=gemini-1.5-pro
DEFAULT_LLM_BASE_URL=your-gcp-project-id
DEFAULT_LLM_API_KEY=us-central1
# GCP credentials via GOOGLE_APPLICATION_CREDENTIALS
```

#### Gemini (Direct API) Configuration

**Environment Variable:**
```env
DEFAULT_LLM_PROVIDER=gemini
DEFAULT_LLM_API_KEY=your-gemini-api-key
DEFAULT_LLM_MODEL=gemini-1.5-pro
```

**In the Application UI:**
```json
{
  "provider": "gemini",
  "api_key": "your-gemini-api-key",
  "model": "gemini-1.5-pro"
}
```

---

### Groq

Groq provides extremely fast inference for open-source models.

#### Getting an API Key

1. Go to [Groq Console](https://console.groq.com/)
2. Sign up and create an API key

#### Configuration

**Environment Variable:**
```env
DEFAULT_LLM_PROVIDER=groq
DEFAULT_LLM_API_KEY=your-groq-api-key
DEFAULT_LLM_MODEL=llama-3.1-70b-versatile
```

**In the Application UI:**
```json
{
  "provider": "groq",
  "api_key": "your-groq-api-key",
  "model": "llama-3.1-70b-versatile"
}
```

#### Model Options

| Model | Description |
|-------|-------------|
| `llama-3.1-70b-versatile` | Llama 3.1 70B (recommended) |
| `llama-3.1-8b-instant` | Llama 3.1 8B (fastest) |
| `mixtral-8x7b-32768` | Mixtral 8x7B |

---

### Ollama (Local LLMs)

Run LLMs locally with Ollama for privacy and cost savings.

#### Setup

1. Install [Ollama](https://ollama.ai/)
2. Pull a model: `ollama pull llama3`
3. Start server: `ollama serve`

#### Configuration

**Environment Variable:**
```env
DEFAULT_LLM_PROVIDER=ollama
DEFAULT_LLM_BASE_URL=http://localhost:11434
DEFAULT_LLM_MODEL=llama3
```

**In the Application UI:**
```json
{
  "provider": "ollama",
  "base_url": "http://localhost:11434",
  "model": "llama3"
}
```

#### Recommended Models for SQL Generation

| Model | Parameters | Quality |
|-------|------------|---------|
| `llama3` | 8B | Good |
| `codellama` | 7B | Good for code |
| `mixtral` | 8x7B | Best |

---

### Other Providers

QueryfyAI supports additional providers via LiteLLM:

| Provider | Configuration |
|----------|--------------|
| **Together AI** | `provider: together`, requires `api_key` |
| **Mistral** | `provider: mistral`, requires `api_key` |
| **Cohere** | `provider: cohere`, requires `api_key` |
| **DeepSeek** | `provider: deepseek`, requires `api_key` |
| **Replicate** | `provider: replicate`, requires `api_key` |

Example for Together AI:
```env
DEFAULT_LLM_PROVIDER=together
DEFAULT_LLM_API_KEY=your-together-api-key
DEFAULT_LLM_MODEL=meta-llama/Llama-3-70b-chat-hf
```

---

### OAuth Gateway (Enterprise)

For corporate environments with centralized LLM access through an OAuth-protected gateway.

#### When to Use

- Your organization has a centralized LLM gateway
- Access requires OAuth 2.0 client credentials
- You received client ID/secret from your IT department

#### Getting Your Credentials

Contact your IT department or LLM platform administrator for:
- Gateway base URL
- OAuth token URL
- Client ID
- Client Secret
- Required scope
- Available models

#### Configuration

**Environment Variable:**
```env
DEFAULT_LLM_PROVIDER=oauth_gateway
DEFAULT_LLM_BASE_URL=https://llm-gateway.yourcompany.com
DEFAULT_LLM_TOKEN_URL=https://auth.yourcompany.com/oauth2/token
DEFAULT_LLM_CLIENT_ID=your-client-id
DEFAULT_LLM_CLIENT_SECRET=your-client-secret
DEFAULT_LLM_AUTH_SCOPE=llm.chat
DEFAULT_LLM_AUTH_TYPE=client_credentials
DEFAULT_LLM_MODEL=gpt-4
DEFAULT_LLM_CHAT_ENDPOINT=/v1/chat/completions
```

**In the Application UI:**
```json
{
  "provider": "oauth_gateway",
  "base_url": "https://llm-gateway.yourcompany.com",
  "token_url": "https://auth.yourcompany.com/oauth2/token",
  "client_id": "your-client-id",
  "client_secret": "your-client-secret",
  "auth_scope": "llm.chat",
  "auth_type": "client_credentials",
  "model": "gpt-4",
  "chat_endpoint": "/v1/chat/completions"
}
```

The application handles token refresh automatically.

---

### Custom Endpoint

For self-hosted LLMs or custom API endpoints that follow the OpenAI API format.

#### Use Cases

- Local LLMs (Ollama, LM Studio, vLLM)
- Custom API proxies
- Other OpenAI-compatible endpoints

#### Configuration

**Environment Variable:**
```env
DEFAULT_LLM_PROVIDER=custom
DEFAULT_LLM_BASE_URL=http://localhost:11434
DEFAULT_LLM_CHAT_ENDPOINT=/v1/chat/completions
DEFAULT_LLM_MODEL=llama2
# API key is optional for local endpoints
# DEFAULT_LLM_API_KEY=optional-key
```

**In the Application UI:**
```json
{
  "provider": "custom",
  "base_url": "http://localhost:11434",
  "chat_endpoint": "/v1/chat/completions",
  "model": "llama2",
  "api_key": ""
}
```

#### Example: Using Ollama

1. Install [Ollama](https://ollama.ai/)
2. Pull a model: `ollama pull llama2`
3. Run Ollama: `ollama serve`
4. Configure QueryfyAI:
   ```json
   {
     "provider": "custom",
     "base_url": "http://localhost:11434",
     "chat_endpoint": "/api/chat",
     "model": "llama2"
   }
   ```

---

## Database Configuration

QueryfyAI can connect to multiple database types. Configure your database in the application's settings.

### Connection URL Format

All databases use a connection URL format:
```
driver://username:password@host:port/database?options
```

**Security Note:** Your database credentials are stored in your session only. They are never logged or stored on the server.

---

### PostgreSQL

The most popular open-source relational database.

#### Connection URL Format
```
postgresql://username:password@host:port/database
```

#### Examples

**Local PostgreSQL:**
```
postgresql://postgres:mypassword@localhost:5432/mydb
```

**Remote PostgreSQL:**
```
postgresql://user:pass@db.example.com:5432/production
```

**With SSL:**
```
postgresql://user:pass@host:5432/db?sslmode=require
```

#### Quick Setup with Docker

Run a PostgreSQL instance for testing:
```bash
docker run -d \
  --name postgres-test \
  -e POSTGRES_USER=testuser \
  -e POSTGRES_PASSWORD=testpass \
  -e POSTGRES_DB=testdb \
  -p 5432:5432 \
  postgres:15

# Connection URL:
# postgresql://testuser:testpass@localhost:5432/testdb
```

#### Common Connection Issues

| Issue | Solution |
|-------|----------|
| "Connection refused" | Ensure PostgreSQL is running and accepting connections |
| "Password authentication failed" | Verify username and password |
| "Database does not exist" | Create the database first |
| "SSL required" | Add `?sslmode=require` to the URL |

---

### MySQL

Popular relational database, common in web applications.

#### Connection URL Format
```
mysql://username:password@host:port/database
```

#### Examples

**Local MySQL:**
```
mysql://root:mypassword@localhost:3306/mydb
```

**Remote MySQL:**
```
mysql://user:pass@db.example.com:3306/production
```

#### Quick Setup with Docker

```bash
docker run -d \
  --name mysql-test \
  -e MYSQL_ROOT_PASSWORD=rootpass \
  -e MYSQL_USER=testuser \
  -e MYSQL_PASSWORD=testpass \
  -e MYSQL_DATABASE=testdb \
  -p 3306:3306 \
  mysql:8

# Connection URL:
# mysql://testuser:testpass@localhost:3306/testdb
```

---

### SQL Server

Microsoft SQL Server, including Azure SQL Database.

#### Connection URL Format
```
mssql://username:password@host:port/database
```

#### Examples

**Local SQL Server:**
```
mssql://sa:YourPassword123@localhost:1433/mydb
```

**Azure SQL Database:**
```
mssql://user@server:password@server.database.windows.net:1433/mydb?encrypt=true
```

#### Quick Setup with Docker

```bash
docker run -d \
  --name sqlserver-test \
  -e "ACCEPT_EULA=Y" \
  -e "SA_PASSWORD=YourStrong!Password" \
  -p 1433:1433 \
  mcr.microsoft.com/mssql/server:2022-latest

# Connection URL:
# mssql://sa:YourStrong!Password@localhost:1433/master
```

**Note:** SQL Server password must meet complexity requirements (uppercase, lowercase, number, special character, 8+ characters).

---

### Oracle

Oracle Database for enterprise environments.

#### Connection URL Format
```
oracle://username:password@host:port/service_name
```

#### Examples

**With Service Name:**
```
oracle://system:password@localhost:1521/ORCLCDB
```

**With SID (older format):**
```
oracle://system:password@localhost:1521/ORCL
```

#### Notes

- Oracle requires the `cx_Oracle` driver and Oracle Instant Client
- Contact your DBA for connection details
- Service names are case-sensitive

---

### Snowflake

Cloud data warehouse popular for analytics.

#### Connection URL Format
```
snowflake://username:password@account/database/schema?warehouse=WAREHOUSE_NAME
```

#### Finding Your Account Identifier

Your account identifier is in your Snowflake URL:
- URL: `https://abc12345.us-east-1.snowflakecomputing.com`
- Account: `abc12345.us-east-1`

#### Examples

```
snowflake://myuser:mypass@abc12345.us-east-1/MYDB/PUBLIC?warehouse=COMPUTE_WH
```

#### Required Permissions

Your Snowflake user needs:
- `USAGE` on the warehouse
- `USAGE` on the database and schema
- `SELECT` on tables you want to query

---

### BigQuery

Google Cloud's serverless data warehouse.

#### Connection URL Format
```
bigquery://project-id/dataset
```

#### Authentication Setup

BigQuery uses Google Cloud service accounts:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Navigate to **IAM & Admin** > **Service Accounts**
3. Create a new service account
4. Grant the **BigQuery Data Viewer** and **BigQuery Job User** roles
5. Create and download a JSON key file
6. Set the environment variable:
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
   ```

#### Example

```
bigquery://my-gcp-project/my_dataset
```

---

### MongoDB

NoSQL document database.

#### Connection URL Format
```
mongodb://username:password@host:port/database
```

#### Examples

**Local MongoDB:**
```
mongodb://localhost:27017/mydb
```

**With Authentication:**
```
mongodb://user:pass@localhost:27017/mydb?authSource=admin
```

**MongoDB Atlas (Cloud):**
```
mongodb+srv://user:pass@cluster.abc123.mongodb.net/mydb
```

#### Quick Setup with Docker

```bash
docker run -d \
  --name mongo-test \
  -e MONGO_INITDB_ROOT_USERNAME=admin \
  -e MONGO_INITDB_ROOT_PASSWORD=adminpass \
  -p 27017:27017 \
  mongo:7

# Connection URL:
# mongodb://admin:adminpass@localhost:27017/testdb?authSource=admin
```

#### Notes

- MongoDB queries are translated differently than SQL databases
- QueryfyAI generates MongoDB aggregation pipelines
- Some SQL concepts may not translate directly

---

### Cassandra

Apache Cassandra, a distributed NoSQL database for wide-column data.

#### Connection URL Format
```
cassandra://username:password@host:port/keyspace
```

#### Examples

**Local Cassandra:**
```
cassandra://localhost:9042/my_keyspace
```

**With Authentication:**
```
cassandra://cassandra:cassandra@localhost:9042/my_keyspace
```

**Multi-node Cluster:**
```
cassandra://user:pass@node1.example.com:9042/my_keyspace
```

#### Quick Setup with Docker

```bash
docker run -d \
  --name cassandra-test \
  -e CASSANDRA_CLUSTER_NAME=TestCluster \
  -p 9042:9042 \
  cassandra:4.1

# Wait for Cassandra to start (takes ~60 seconds)
sleep 60

# Create a keyspace
docker exec -it cassandra-test cqlsh -e "
  CREATE KEYSPACE IF NOT EXISTS test_keyspace
  WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};
"

# Connection URL: cassandra://localhost:9042/test_keyspace
```

Or use the provided NoSQL Docker Compose:
```bash
docker compose -f docker-compose.nosql.yml up -d cassandra
```

#### Notes

- Cassandra uses CQL (Cassandra Query Language), similar to SQL
- Partition keys are required in WHERE clauses for efficient queries
- QueryfyAI will warn about queries that require ALLOW FILTERING

---

### DynamoDB

Amazon DynamoDB, a serverless key-value and document database.

#### Connection URL Format
```
dynamodb://region/
dynamodb://access_key:secret_key@region/
dynamodb://localhost:8000/  (local)
```

#### Examples

**Using Default AWS Credentials:**
```
dynamodb://us-east-1/
```

**With Explicit Credentials:**
```
dynamodb://EXAMPLE_AWS_ACCESS_KEY_ID:wJalrXUtnFEMI/K7MDENG@us-east-1/
```

**Local DynamoDB:**
```
dynamodb://localhost:8000/
```

#### Quick Setup with Docker (DynamoDB Local)

```bash
docker run -d \
  --name dynamodb-local \
  -p 8000:8000 \
  amazon/dynamodb-local:latest \
  -jar DynamoDBLocal.jar -sharedDb -inMemory

# Connection URL: dynamodb://localhost:8000/
```

Or use the provided NoSQL Docker Compose:
```bash
docker compose -f docker-compose.nosql.yml up -d dynamodb dynamodb-admin
```

This also starts the DynamoDB Admin UI at `http://localhost:8001`.

#### Authentication Options

| Method | Configuration |
|--------|--------------|
| **Default Credentials** | Uses `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` environment variables |
| **IAM Role** | Automatic when running on AWS (EC2, ECS, Lambda) |
| **Explicit Credentials** | Include in connection URL |
| **Local DynamoDB** | No credentials required |

#### Notes

- DynamoDB uses PartiQL, a SQL-compatible query language
- Partition key is required for efficient queries
- QueryfyAI warns about scan operations (which read the entire table)
- GSI (Global Secondary Index) queries are supported

---

### DuckDB

Embedded analytical database, great for analytics and Parquet/CSV files.

#### Connection URL Format
```
duckdb:///path/to/database.duckdb
duckdb://:memory:
```

#### Examples

**File-based DuckDB:**
```
duckdb:///home/user/analytics.duckdb
```

**In-memory (for testing):**
```
duckdb://:memory:
```

**Query Parquet files directly:**
```sql
-- After connecting, you can query Parquet files directly
SELECT * FROM 'data/*.parquet'
```

#### When to Use DuckDB

- Local analytics and data exploration
- Querying Parquet, CSV, or JSON files directly
- Development and testing without external database
- Embedded analytics in applications

---

### SQLite

Lightweight embedded database, built into Python.

#### Connection URL Format
```
sqlite:///path/to/database.db
sqlite:///:memory:
```

#### Examples

**File-based SQLite:**
```
sqlite:///home/user/mydata.db
```

**In-memory (for testing):**
```
sqlite:///:memory:
```

#### Quick Setup (No Docker Required)

SQLite requires no server. Create a database file:
```bash
# Create a simple test database
sqlite3 test.db "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT);"
sqlite3 test.db "INSERT INTO users VALUES (1, 'Alice', 'alice@example.com');"

# Connection URL: sqlite:///test.db
```

#### When to Use SQLite

- Local development and testing
- Demo environments
- Simple applications with local data
- Embedded applications

---

## Context Studio

Context Studio is a visual interface for managing your database's data dictionary - adding business descriptions, glossary terms, and metadata to improve SQL generation accuracy.

### Accessing Context Studio

1. Click the **Context Studio** button in the header (or use the gear icon menu)
2. The Context Studio panel slides in from the right

### Features

| Feature | Description |
|---------|-------------|
| **Table Descriptions** | Add business context to tables (e.g., "Customer orders with line items") |
| **Column Descriptions** | Describe what columns represent in business terms |
| **Business Glossary** | Define terms like "Active Customer" = "Customers with orders in last 90 days" |
| **Relationships** | Document table relationships for better JOIN suggestions |
| **Sample Values** | View column value samples for context |

### How It Improves SQL Generation

When you add descriptions to your schema:

```
Table: customer_orders
Description: "Contains all customer purchase orders. An order can have multiple line items."

Column: status
Description: "Order status: 'pending', 'processing', 'shipped', 'delivered', 'cancelled'"
```

The LLM uses this context to generate more accurate SQL:

```
User: "Show me all active orders"
→ SELECT * FROM customer_orders WHERE status IN ('pending', 'processing', 'shipped')
```

### Data Dictionary API

Context Studio persists to PostgreSQL when `DATABASE_URL` is configured:

```bash
# Ensure migrations are run
cd backend
alembic upgrade head
```

### Import/Export

Context Studio supports bulk import and export of data dictionary entries:

**Export:**
1. Open Context Studio
2. Click the **Export** tab
3. Select format (JSON or CSV)
4. Download the file

**Import:**
1. Open Context Studio
2. Click the **Import** tab
3. Upload your JSON/CSV file
4. Review and confirm the import

**JSON Format Example:**
```json
{
  "tables": [
    {
      "name": "customers",
      "description": "Customer master data",
      "columns": [
        {"name": "id", "description": "Primary key"},
        {"name": "status", "description": "active, inactive, suspended"}
      ]
    }
  ],
  "glossary": [
    {"term": "Active Customer", "definition": "Customer with order in last 90 days"}
  ]
}
```

### Query Patterns (Few-Shot Learning)

Context Studio also supports defining query patterns for few-shot learning:

1. Open Context Studio → **Query Patterns** tab
2. Add example question/SQL pairs
3. The LLM uses these as examples when generating similar queries

**Example Pattern:**
```
Question: "Show top customers by revenue"
SQL: SELECT customer_id, SUM(amount) as total FROM orders GROUP BY customer_id ORDER BY total DESC LIMIT 10
```

### Best Practices

1. **Start with key tables**: Focus on frequently queried tables first
2. **Use business language**: Describe tables/columns as business users understand them
3. **Document edge cases**: Note any special values or business rules
4. **Add examples**: Sample values help the LLM understand data formats
5. **Export regularly**: Backup your data dictionary using the export feature

---

## Vector Database Setup

QueryfyAI uses a vector database to store schema embeddings for intelligent context retrieval. This helps the LLM understand your database structure.

### ChromaDB (Default)

ChromaDB is the default vector database. It runs embedded within the application and requires no additional setup.

#### Configuration

ChromaDB is enabled by default. No configuration needed.

In `backend/.env`:
```env
VECTOR_DB_TYPE=chromadb
CHROMA_PERSIST_DIR=./data/chroma_db
```

#### When to Use ChromaDB

- Local development
- Small to medium deployments
- Single-server setups
- Quick start without additional infrastructure

#### Data Location

ChromaDB stores data in `backend/data/chroma_db/`. This directory is created automatically.

---

### Qdrant

Qdrant is a high-performance vector database for production deployments.

#### When to Use Qdrant

- Production environments
- Large database schemas
- Multiple QueryfyAI instances
- Need for advanced vector search features

#### Setup with Docker

```bash
docker run -d \
  --name qdrant \
  -p 6333:6333 \
  -v qdrant_storage:/qdrant/storage \
  qdrant/qdrant
```

#### Configuration

In `backend/.env`:
```env
VECTOR_DB_TYPE=qdrant
QDRANT_URL=http://localhost:6333
# Optional: API key for Qdrant Cloud
# QDRANT_API_KEY=your-api-key
```

#### Qdrant Cloud

For managed Qdrant:
1. Sign up at [Qdrant Cloud](https://cloud.qdrant.io/)
2. Create a cluster
3. Get your URL and API key
4. Configure:
   ```env
   QDRANT_URL=https://your-cluster.qdrant.io
   QDRANT_API_KEY=your-api-key
   ```

---

## Loading Sample Data

To test QueryfyAI, you can load sample data into your database.

### Option 1: PostgreSQL Sample Database (Chinook)

The Chinook database represents a digital media store with customers, invoices, and music tracks.

```bash
# 1. Start PostgreSQL (if not running)
docker run -d \
  --name postgres-chinook \
  -e POSTGRES_USER=demo \
  -e POSTGRES_PASSWORD=demo \
  -e POSTGRES_DB=chinook \
  -p 5432:5432 \
  postgres:15

# 2. Wait for PostgreSQL to start
sleep 5

# 3. Download and load Chinook
curl -L https://raw.githubusercontent.com/lerocha/chinook-database/master/ChinookDatabase/DataSources/Chinook_PostgreSql.sql -o chinook.sql

docker exec -i postgres-chinook psql -U demo -d chinook < chinook.sql

# Connection URL: postgresql://demo:demo@localhost:5432/chinook
```

**Sample Queries to Try:**
- "Show me all customers from the USA"
- "What are the top 10 best-selling tracks?"
- "Total sales by country"
- "List all albums by artist name"

### Option 2: MySQL Sample Database (Sakila)

The Sakila database represents a DVD rental store.

```bash
# 1. Start MySQL
docker run -d \
  --name mysql-sakila \
  -e MYSQL_ROOT_PASSWORD=demo \
  -e MYSQL_DATABASE=sakila \
  -p 3306:3306 \
  mysql:8

# 2. Wait for MySQL to start
sleep 10

# 3. Download and load Sakila
curl -L https://downloads.mysql.com/docs/sakila-db.tar.gz -o sakila.tar.gz
tar -xzf sakila.tar.gz
docker exec -i mysql-sakila mysql -uroot -pdemo sakila < sakila-db/sakila-schema.sql
docker exec -i mysql-sakila mysql -uroot -pdemo sakila < sakila-db/sakila-data.sql

# Connection URL: mysql://root:demo@localhost:3306/sakila
```

### Option 3: Using Your Own Data

1. Set up your database connection in QueryfyAI
2. Click "Refresh Schema" to extract your database structure
3. The application will automatically index your tables and columns
4. Start asking questions about your data

**Tips for Better Results:**
- Use descriptive table and column names
- Add comments/descriptions to tables and columns in your database
- The LLM learns from your schema names

---

## Using the Application

### First-Time Setup

1. **Open the Application**
   - Development: `http://localhost:5173`
   - Production: Your deployed URL

2. **Configure LLM Provider**
   - Click the **Settings** button (gear icon in the top right)
   - Select your LLM provider (OpenAI, Anthropic, etc.)
   - Enter your API credentials
   - Click **Test Connection** to verify

3. **Configure Database Connection**
   - In Settings, go to the Database section
   - Select your database type
   - Enter your connection URL
   - Click **Test Connection** to verify

4. **Refresh Schema** (First time only)
   - After connecting, click **Refresh Schema**
   - This extracts your database structure
   - Wait for the process to complete

### Main Interface

```
┌─────────────────────────────────────────────────────────┐
│  QueryfyAI                              [Settings] [?]  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Ask a question about your data...                 │  │
│  │                                          [Submit] │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │ [SQL] [Table] [Chart]                             │  │
│  │                                                   │  │
│  │  Results appear here...                           │  │
│  │                                                   │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │ History                                           │  │
│  │ • Show me top 10 customers          [Replay]      │  │
│  │ • Total sales by month              [Replay]      │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Asking Questions

1. Type your question in natural language
2. Press **Enter** or click **Submit**
3. The generated SQL appears in the SQL tab
4. Click **Execute** to run the query
5. View results in the **Table** or **Chart** tab

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl + Enter` | Submit query |
| `Escape` | Clear input |

### Tips for Better Queries

**Be Specific:**
- Instead of: "Show me data"
- Try: "Show me all customers who made purchases last month"

**Include Filters:**
- Instead of: "Show orders"
- Try: "Show orders over $1000 from the last 30 days"

**Reference Table Names:**
- If you know your tables: "Show me data from the users table"

**Ask for Aggregations:**
- "Count of orders by status"
- "Average order value by customer"
- "Total revenue by month"

### Understanding Results

**SQL Tab:** Shows the generated SQL query. You can:
- Review before executing
- Copy the SQL for use elsewhere
- Get an explanation of what the query does

**Table Tab:** Shows query results in a spreadsheet format. You can:
- Sort columns by clicking headers
- Export to Excel

**Chart Tab:** Shows automatic visualization. The system:
- Detects the best chart type for your data
- Provides alternative chart options
- Supports bar, line, pie, scatter, and more

---

## Using Analysis Features

QueryfyAI's analyst mode provides rich insights beyond basic SQL generation.

### Intelligent Insights

The system automatically detects patterns and anomalies in your data:

**Types of Insights:**
- **Patterns**: "Revenue follows a weekly cycle with peaks on Fridays"
- **Anomalies**: "Customer #1042 has 10x higher order value than average"
- **Trends**: "Sales increased 23% compared to last quarter"
- **Correlations**: "High customer satisfaction scores correlate with repeat purchases"

**Severity Levels:**
- 🔴 **Critical**: Requires immediate attention
- 🟡 **Warning**: Notable finding
- 🔵 **Info**: General observation

**Example Response:**
```json
{
  "key_findings": [
    "[CRITICAL] Customer #1042 revenue is 10x higher than average ($250K vs $25K)",
    "[WARNING] 15% of orders have null shipping addresses",
    "[INFO] Top 3 customers account for 45% of total revenue"
  ],
  "confidence": 0.92
}
```

### Data Quality Scoring

Every analyst mode response includes a data quality assessment:

**Quality Metrics:**
- **Overall Score** (0-100): Composite quality score
- **Completeness** (%): Percentage of non-null values
- **Issues Detected**: Specific problems found

**Example:**
```json
{
  "data_quality": {
    "overall_score": 85,
    "completeness": 92,
    "issues": [
      "8% missing customer email addresses",
      "Date range has 2-day gap (2024-03-15 to 2024-03-16)"
    ]
  }
}
```

**Interpretation:**
- **90-100**: Excellent quality, high confidence
- **70-89**: Good quality, minor issues
- **50-69**: Fair quality, notable gaps
- **<50**: Poor quality, use with caution

### Follow-Up Questions

Analyst mode supports natural follow-up questions with context awareness:

**Follow-up Examples:**
| Initial Question | Follow-up | How It Works |
|-----------------|-----------|--------------|
| "Show me Q4 sales" | "Now filter those by region='West'" | Agent references previous SQL |
| "Top customers by revenue" | "What about year-over-year growth?" | Agent adds comparison logic |
| "Order trends" | "Break that down by product category" | Agent modifies GROUP BY |

**Conversation Turn Counter:**
The UI shows "Turn 1", "Turn 2", etc. to track conversation flow.

**Best Practices:**
- Use pronouns: "it", "those", "them"
- Reference previous results: "the same data", "last query"
- Add filters incrementally: "now only show...", "filter by..."

### Chart Intelligence

Charts are automatically generated based on data characteristics:

**Chart Type Selection:**
| Data Pattern | Recommended Chart | Example |
|--------------|------------------|---------|
| Single metric | **Gauge** | Total revenue: $1.2M |
| Categories + values | **Bar** | Sales by region |
| Time series | **Line** | Revenue over time |
| Parts of whole | **Pie** | Market share by product |
| Two numeric columns | **Scatter** | Revenue vs customer count |
| Geographic data | **Geo/Choropleth** | Sales by state |

**Chart Customization:**
- Change chart type via dropdown
- Adjust colors and labels
- Toggle data labels
- Export as PNG

**Example Chart Spec:**
```json
{
  "chart": {
    "chart_type": "bar",
    "title": "Top 10 Customers by Revenue",
    "x_axis": "customer_id",
    "y_axis": "revenue",
    "x_label": "Customer",
    "y_label": "Revenue ($)",
    "data": [...]
  }
}
```

### Agent Tool Execution

In streaming mode, you can see the agent's reasoning process in real-time:

**Tool Execution Steps:**
1. **search_tables** - Finding relevant tables
2. **get_table_schema** - Retrieving column details
3. **execute_and_analyze** - Running query + analysis
4. **recommend_chart** - Selecting visualization
5. **detect_insights** - Finding patterns

**UI Indicators:**
- ⏳ "Thinking..." - Agent is reasoning
- 🔧 "Using tool: search_tables" - Tool invocation
- ✅ "Found 3 relevant tables" - Tool result
- 📊 "Analyzing results..." - Analysis in progress

### Confidence Scores

Every analyst response includes a confidence score (0.0-1.0):

**Confidence Levels:**
- **0.90-1.00**: Very high confidence, comprehensive results
- **0.70-0.89**: High confidence, good data coverage
- **0.50-0.69**: Medium confidence, some limitations
- **<0.50**: Low confidence, incomplete or ambiguous

**Factors Affecting Confidence:**
- Data completeness (% non-null values)
- Result set size (more rows = higher confidence)
- Schema match quality
- Ambiguity in user question

---

## Production Deployment

For production deployments, QueryfyAI includes Docker configurations and operational tools.

### Quick Production Setup

```bash
# 1. Configure production environment
cp .env.production.example .env.production
# Edit .env.production with your settings

# 2. Generate SSL certificates (optional)
./scripts/generate-certs.sh

# 3. Deploy with Docker Compose
docker-compose -f docker-compose.production.yml up -d
```

### With Monitoring

```bash
docker-compose -f docker-compose.production.yml \
               -f docker-compose.monitoring.yml up -d
```

This adds:
- **Prometheus** (`:9090`) - Metrics collection
- **Grafana** (`:3001`) - Dashboards

### Health Checks

```bash
# Check all services
./scripts/healthcheck.sh

# Backend health
curl http://localhost:8000/health
```

### For More Information

- **Detailed deployment guide:** See [RUNBOOK.md](../RUNBOOK.md)
- **Architecture overview:** See [ARCHITECTURE.md](./ARCHITECTURE.md)
- **Security:** See [SECURITY.md](./SECURITY.md)

---

## Common Commands Reference

A quick reference for all common commands used with QueryfyAI.

### Development

```bash
# Start backend (development mode with hot reload)
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Start frontend (development mode with hot reload)
cd frontend
npm run dev

# Run backend tests
cd backend
pytest

# Run frontend tests
cd frontend
npm run test

# Build frontend for production
cd frontend
npm run build

# Lint and format code
cd backend
ruff check . --fix
ruff format .

cd frontend
npm run lint
```

### Database Migrations (Alembic)

```bash
cd backend

# Apply all pending migrations
alembic upgrade head

# Check current version
alembic current

# View migration history
alembic history

# Create new migration (auto-detect changes)
alembic revision --autogenerate -m "description"

# Rollback one migration
alembic downgrade -1

# Rollback all migrations
alembic downgrade base

# Mark database as current (skip migrations)
alembic stamp head
```

### Docker Operations

```bash
# Development stack
docker-compose up -d
docker-compose logs -f backend

# Production stack
docker-compose -f docker-compose.production.yml up -d

# With monitoring (Prometheus, Grafana, Jaeger)
docker-compose -f docker-compose.production.yml \
               -f docker-compose.monitoring.yml up -d

# Rebuild images
docker-compose build --no-cache

# View logs
docker-compose logs -f backend
docker-compose logs -f frontend

# Execute command in container
docker exec -it queryfyai-backend alembic upgrade head
docker exec -it queryfyai-backend python -c "print('hello')"

# Stop all containers
docker-compose down

# Stop and remove volumes
docker-compose down -v
```

### Kubernetes Operations

```bash
# Apply manifests
kubectl apply -k k8s/

# Check deployment status
kubectl get pods -n queryfyai
kubectl get svc -n queryfyai

# View logs
kubectl logs -f deploy/queryfyai-backend -n queryfyai

# Execute command in pod
kubectl exec -it deploy/queryfyai-backend -n queryfyai -- alembic upgrade head

# Port forward for local access
kubectl port-forward svc/queryfyai-backend 8000:8000 -n queryfyai
kubectl port-forward svc/queryfyai-frontend 3000:80 -n queryfyai

# Scale deployment
kubectl scale deploy/queryfyai-backend --replicas=3 -n queryfyai

# Rolling restart
kubectl rollout restart deploy/queryfyai-backend -n queryfyai
```

### Health Checks

```bash
# Backend health
curl http://localhost:8000/health
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready

# Prometheus metrics
curl http://localhost:8000/metrics

# Test database connection (in container)
docker exec -it queryfyai-backend python -c "
from app.core.config import settings
print(f'Database URL: {settings.DATABASE_URL[:50]}...')
"
```

### Useful Scripts

```bash
# Generate SSL certificates
./scripts/generate-certs.sh

# Full health check
./scripts/healthcheck.sh

# Backup ChromaDB data
./scripts/backup.sh

# Restore from backup
./scripts/restore.sh backup-2024-01-01.tar.gz

# Deploy with zero downtime
./scripts/deploy.sh
```

---

## Troubleshooting Quick Reference

### Common Issues

| Issue | Quick Fix |
|-------|-----------|
| Backend won't start | Check `.env` file exists and has valid LLM config |
| "Network Error" in frontend | Ensure backend is running on port 8000 |
| CORS errors | Set `ALLOWED_ORIGINS` in backend `.env` |
| "Connection refused" to database | Verify database is running and URL is correct |
| Slow query generation | Check LLM provider status; first query is slower |
| "Invalid API key" | Verify API key is correct and has not expired |
| No charts showing | Ensure results have numeric columns |

### Diagnostic Commands

```bash
# Check if backend is running
curl http://localhost:8000/health

# Check backend logs (Docker)
docker logs queryfy-backend --tail 100

# Check frontend is accessible
curl http://localhost:5173

# Test database connection (from backend container)
docker exec queryfy-backend python -c "
import asyncpg
import asyncio
asyncio.run(asyncpg.connect('your-connection-url'))
print('Connected!')
"
```

### Getting Help

1. Review backend logs for detailed error messages
2. Ensure all prerequisites are installed correctly
3. Verify your LLM and database credentials
4. See [AGENT_REFERENCE.md](./AGENT_REFERENCE.md) for agent troubleshooting

---

## Database Connection URL Quick Reference

| Database | URL Format |
|----------|------------|
| PostgreSQL | `postgresql://user:pass@host:5432/db` |
| MySQL | `mysql://user:pass@host:3306/db` |
| SQL Server | `mssql://user:pass@host:1433/db` |
| Oracle | `oracle://user:pass@host:1521/SERVICE` |
| MongoDB | `mongodb://user:pass@host:27017/db` |
| DuckDB | `duckdb:///path/to/db.duckdb` or `duckdb://:memory:` |
| SQLite | `sqlite:///path/to/db.sqlite` or `sqlite:///:memory:` |
| Snowflake | `snowflake://user:pass@account/db/schema?warehouse=WH` |
| BigQuery | `bigquery://project-id/dataset` |
| Cassandra | `cassandra://user:pass@host:9042/keyspace` |
| DynamoDB | `dynamodb://region/` or `dynamodb://localhost:8000/` |
| ClickHouse | `clickhouse://user:pass@host:8123/db` |
| Trino | `trino://user@host:8080/catalog/schema` |
| Presto | `presto://user@host:8080/catalog/schema` |
| Athena | `athena://region/?s3_staging_dir=s3://bucket/path` |
| Redshift | `redshift://user:pass@cluster.region.redshift.amazonaws.com:5439/db` |
| Databricks | `databricks://token:TOKEN@host/?http_path=/sql/1.0/warehouses/ID` |
| Hive | `hive://host:10000/db` |
| Spark | `spark://host:10000/db` |

---

## Next Steps

Now that you're set up, try these:

1. **Explore your data:** Ask questions about different tables
2. **Try different visualizations:** The Chart tab auto-detects the best chart
3. **Review query history:** Use the History panel to see past queries
4. **Export results:** Download query results as Excel files
5. **Fine-tune:** Adjust LLM models based on accuracy and speed needs

Happy querying!
