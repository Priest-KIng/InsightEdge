# Organization LAN Deployment Notes

InsightEdge can run as a small, single-organization client/server deployment. A server inside the organization hosts the frontend, FastAPI service, local vector database, SQLite state, and Ollama. Employee browsers connect to that server; documents and prompts are processed there, and Ollama should remain bound to loopback on the server.

```text
Employee browsers -> HTTPS reverse proxy -> InsightEdge frontend + API -> local ChromaDB / SQLite
                                                               \-> Ollama on the server GPU
```

## First deployment boundary

The organization login in this version uses one account configured on the server. Every signed-in person can access the same workspaces and documents. It is an access gate for a trusted private network, not an identity provider or a multi-tenant boundary. Anyone with access to the server's data directory can read the local indexes and state.

Configure these values in the backend `.env` file:

```text
AUTH_USERNAME=insightedge-user
AUTH_PASSWORD=<long-unique-password>
AUTH_SIGNING_SECRET=<random-secret-of-at-least-32-bytes>
AUTH_SESSION_MINUTES=480
```

The token signing secret is private server configuration. Rotating it invalidates all active browser sessions. The frontend keeps tokens in session storage; the server validates each token on protected chat and ingestion requests.

## Development LAN trial

For a limited internal trial, bind the frontend and backend to the server's LAN interfaces and set the browser API URL to that server. Example for a server at `10.20.30.40`:

```text
# frontend/.env, read at build/dev-server startup
VITE_API_BASE_URL=http://10.20.30.40:8000/api

# backend/.env
CORS_ORIGINS=["http://10.20.30.40:5173"]
```

Start the development servers with `uvicorn app.main:app --host 0.0.0.0 --port 8000` and `npm run dev -- --host 0.0.0.0`. Restart each process after changing its environment. Restrict both ports with the host firewall to the organization's private network. Development servers are not intended for broad deployment.

## Before wider access

- Put the frontend and API behind an HTTPS reverse proxy. Do not send login passwords or bearer tokens over unencrypted HTTP.
- Do not expose Ollama's port `11434` to employee networks or the internet; the backend should call Ollama over loopback.
- Use VPN/firewall rules and rate limiting at the proxy. This prototype does not implement login throttling, account lockout, individual roles, SSO, or token revocation.
- Back up the local vector database and SQLite state using an organization-approved encrypted backup process. Define retention and deletion rules for uploaded material.
- For real multi-user deployment, integrate the organization's identity provider, enforce document-level authorization at the backend, and record user identity in audit events before adding any collaboration/sharing feature.

## Privacy boundary

The browser sends requests to the configured organization server. The server performs file extraction, embeddings, retrieval, and model generation using the local Ollama endpoint. The default project path does not call hosted AI APIs, but network administrators should still review reverse-proxy logs, backup systems, and any custom embedding/model providers before placing sensitive documents on it.
