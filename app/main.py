import logging
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.webhooks import router as webhooks_router
from app.api.dashboard import router as dashboard_router
from app.config.settings import settings
from app.models.database import init_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("app.main")

# Initialize database
try:
    init_db()
    logger.info("Database initialized successfully.")
except Exception as e:
    logger.error(f"Database initialization failed: {e}")

app = FastAPI(
    title="AI Pull Request Reviewer",
    description="LangGraph-powered production GitHub code reviewer",
    version="1.0.0"
)

# Set up CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(webhooks_router, prefix="/api/v1/webhooks", tags=["Webhooks"])
app.include_router(dashboard_router, prefix="/api/v1/analytics", tags=["Dashboard / Analytics"])
# Note: For simplicity and grouping, we combine dashboard_router endpoints under /api/v1
app.include_router(dashboard_router, prefix="/api/v1/indexer", tags=["Indexer"])


@app.get("/", response_class=HTMLResponse)
def index():
    """Renders a premium visual landing page and system status dashboard."""
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AI-Powered GitHub Pull Request Reviewer</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=Plus+Jakarta+Sans:wght@300;400;600;700&display=swap" rel="stylesheet">
        <style>
            :root {
                --bg-dark: #0a0c10;
                --bg-panel: rgba(18, 22, 30, 0.7);
                --border-color: rgba(255, 255, 255, 0.08);
                --primary: #8b5cf6;
                --primary-glow: rgba(139, 92, 246, 0.4);
                --secondary: #10b981;
                --secondary-glow: rgba(16, 185, 129, 0.4);
                --accent: #3b82f6;
                --text-main: #f3f4f6;
                --text-muted: #9ca3af;
                --font-headers: 'Outfit', sans-serif;
                --font-body: 'Plus Jakarta Sans', sans-serif;
            }

            * {
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }

            body {
                background-color: var(--bg-dark);
                color: var(--text-main);
                font-family: var(--font-body);
                line-height: 1.6;
                overflow-x: hidden;
                background-image: 
                    radial-gradient(circle at 10% 20%, rgba(139, 92, 246, 0.05) 0%, transparent 40%),
                    radial-gradient(circle at 90% 80%, rgba(59, 130, 246, 0.05) 0%, transparent 40%);
            }

            header {
                padding: 2rem 4rem;
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 1px solid var(--border-color);
                backdrop-filter: blur(10px);
                position: sticky;
                top: 0;
                z-index: 100;
                background: rgba(10, 12, 16, 0.8);
            }

            .logo-container {
                display: flex;
                align-items: center;
                gap: 10px;
            }

            .logo-icon {
                width: 36px;
                height: 36px;
                background: linear-gradient(135deg, var(--primary), var(--accent));
                border-radius: 8px;
                display: flex;
                align-items: center;
                justify-content: center;
                box-shadow: 0 0 20px var(--primary-glow);
                font-weight: 800;
                font-family: var(--font-headers);
                font-size: 1.2rem;
            }

            .logo-text {
                font-family: var(--font-headers);
                font-size: 1.4rem;
                font-weight: 700;
                background: linear-gradient(135deg, #ffffff, #9ca3af);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }

            .status-badge {
                display: flex;
                align-items: center;
                gap: 8px;
                background: rgba(16, 185, 129, 0.1);
                border: 1px solid rgba(16, 185, 129, 0.2);
                padding: 6px 14px;
                border-radius: 50px;
                font-size: 0.85rem;
                font-weight: 600;
                color: var(--secondary);
            }

            .status-dot {
                width: 8px;
                height: 8px;
                background-color: var(--secondary);
                border-radius: 50%;
                box-shadow: 0 0 10px var(--secondary);
                animation: pulse 2s infinite;
            }

            .hero {
                max-width: 1200px;
                margin: 4rem auto;
                padding: 0 2rem;
                text-align: center;
            }

            .hero h1 {
                font-family: var(--font-headers);
                font-size: 3.5rem;
                font-weight: 800;
                line-height: 1.2;
                margin-bottom: 1.5rem;
                background: linear-gradient(135deg, #ffffff 30%, #a78bfa 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }

            .hero p {
                font-size: 1.2rem;
                color: var(--text-muted);
                max-width: 700px;
                margin: 0 auto 2.5rem auto;
            }

            .btn {
                display: inline-block;
                padding: 12px 28px;
                border-radius: 8px;
                font-weight: 600;
                text-decoration: none;
                transition: all 0.3s ease;
                font-family: var(--font-headers);
                cursor: pointer;
            }

            .btn-primary {
                background: linear-gradient(135deg, var(--primary), var(--accent));
                color: #ffffff;
                box-shadow: 0 4px 20px var(--primary-glow);
                border: none;
            }

            .btn-primary:hover {
                transform: translateY(-2px);
                box-shadow: 0 6px 24px rgba(139, 92, 246, 0.6);
            }

            .btn-outline {
                background: transparent;
                border: 1px solid var(--border-color);
                color: var(--text-main);
                margin-left: 1rem;
            }

            .btn-outline:hover {
                background: rgba(255, 255, 255, 0.05);
                border-color: rgba(255, 255, 255, 0.2);
            }

            .dashboard-preview {
                max-width: 1100px;
                margin: 4rem auto;
                padding: 2rem;
                background: var(--bg-panel);
                border: 1px solid var(--border-color);
                border-radius: 16px;
                backdrop-filter: blur(12px);
                box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
            }

            .dashboard-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 2rem;
                border-bottom: 1px solid var(--border-color);
                padding-bottom: 1rem;
            }

            .dashboard-title {
                font-family: var(--font-headers);
                font-size: 1.2rem;
                font-weight: 600;
                color: #ffffff;
            }

            .metrics-grid {
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 1.5rem;
                margin-bottom: 2rem;
            }

            .metric-card {
                background: rgba(255, 255, 255, 0.02);
                border: 1px solid var(--border-color);
                border-radius: 12px;
                padding: 1.5rem;
                text-align: left;
                transition: transform 0.3s ease;
            }

            .metric-card:hover {
                transform: translateY(-4px);
                border-color: rgba(139, 92, 246, 0.3);
            }

            .metric-label {
                font-size: 0.85rem;
                color: var(--text-muted);
                margin-bottom: 5px;
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }

            .metric-value {
                font-family: var(--font-headers);
                font-size: 2rem;
                font-weight: 700;
            }

            .metric-value.purple { color: #a78bfa; }
            .metric-value.green { color: #34d399; }
            .metric-value.blue { color: #60a5fa; }
            .metric-value.yellow { color: #fbbf24; }

            .workflow-section {
                max-width: 1200px;
                margin: 6rem auto;
                padding: 0 2rem;
            }

            .workflow-section h2 {
                font-family: var(--font-headers);
                font-size: 2.2rem;
                text-align: center;
                margin-bottom: 4rem;
            }

            .workflow-grid {
                display: grid;
                grid-template-columns: repeat(5, 1fr);
                gap: 1rem;
                position: relative;
            }

            .workflow-card {
                background: var(--bg-panel);
                border: 1px solid var(--border-color);
                padding: 1.5rem;
                border-radius: 12px;
                text-align: center;
                position: relative;
                z-index: 2;
                transition: border-color 0.3s;
            }

            .workflow-card:hover {
                border-color: var(--primary);
            }

            .workflow-num {
                width: 30px;
                height: 30px;
                background: rgba(139, 92, 246, 0.15);
                border: 1px solid var(--primary);
                color: var(--primary);
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 1rem auto;
                font-weight: bold;
            }

            .workflow-card h3 {
                font-family: var(--font-headers);
                font-size: 1rem;
                margin-bottom: 8px;
            }

            .workflow-card p {
                font-size: 0.8rem;
                color: var(--text-muted);
            }

            .footer {
                text-align: center;
                padding: 4rem;
                border-top: 1px solid var(--border-color);
                color: var(--text-muted);
                font-size: 0.9rem;
            }

            @keyframes pulse {
                0% {
                    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
                }
                70% {
                    box-shadow: 0 0 0 10px rgba(16, 185, 129, 0);
                }
                100% {
                    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
                }
            }

            @media(max-width: 900px) {
                .metrics-grid {
                    grid-template-columns: repeat(2, 1fr);
                }
                .workflow-grid {
                    grid-template-columns: 1fr;
                    gap: 2rem;
                }
                .hero h1 {
                    font-size: 2.5rem;
                }
            }
        </style>
    </head>
    <body>

        <header>
            <div class="logo-container">
                <div class="logo-icon">PR</div>
                <div class="logo-text">AI Pull Request Reviewer</div>
            </div>
            <div class="status-badge">
                <div class="status-dot"></div>
                System Active
            </div>
        </header>

        <section class="hero">
            <h1>Automated Code Reviews,<br>Powered by LangGraph & Gemini</h1>
            <p>A production-ready agentic code reviewer that runs semantic RAG similarity searches to enforce codebase styles, security regulations, and performance best-practices on every GitHub pull request.</p>
            <div>
                <a href="/docs" class="btn btn-primary">API Documentation</a>
                <a href="https://github.com" target="_blank" class="btn btn-outline">Connect GitHub Repository</a>
            </div>
        </section>

        <section class="dashboard-preview">
            <div class="dashboard-header">
                <div class="dashboard-title">📈 System Statistics (Mock Dashboard)</div>
                <div style="font-size:0.85rem; color:var(--text-muted)">Live Updates</div>
            </div>
            <div class="metrics-grid">
                <div class="metric-card">
                    <div class="metric-label">Reviews Triggered</div>
                    <div class="metric-value purple">148</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Avg Quality Score</div>
                    <div class="metric-value green">8.4<span style="font-size:1.2rem">/10</span></div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Security Flaws Found</div>
                    <div class="metric-value blue">14</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Feedback loop rate</div>
                    <div class="metric-value yellow">94.2%</div>
                </div>
            </div>
            <div style="padding: 1.5rem; background: rgba(255, 255, 255, 0.01); border: 1px solid var(--border-color); border-radius: 8px; text-align: left;">
                <h4 style="font-family: var(--font-headers); margin-bottom: 10px;">📋 Configure Webhooks</h4>
                <p style="color: var(--text-muted); font-size: 0.9rem; margin-bottom: 15px;">To begin automatic reviews, configure a GitHub Webhook with the settings below:</p>
                <code style="display: block; padding: 12px; background: #000; border-radius: 6px; font-family: monospace; color: #a78bfa; font-size: 0.9rem;">
                    Payload URL: [Your Server Domain]/api/v1/webhooks/github <br>
                    Content Type: application/json <br>
                    Secret: [Your Webhook HMAC Secret] <br>
                    Events: Let me select individual events -> Pull Requests, Pull Request Review Comments
                </code>
            </div>
        </section>

        <section class="workflow-section">
            <h2>Core LangGraph Review Workflow</h2>
            <div class="workflow-grid">
                <div class="workflow-card">
                    <div class="workflow-num">1</div>
                    <h3>Webhook Event</h3>
                    <p>Validates and filters incoming pull request event.</p>
                </div>
                <div class="workflow-card">
                    <div class="workflow-num">2</div>
                    <h3>PR Metadata</h3>
                    <p>Gathers base/head commits and developer info.</p>
                </div>
                <div class="workflow-card">
                    <div class="workflow-num">3</div>
                    <h3>Semantic RAG</h3>
                    <p>Queries ChromaDB for coding patterns.</p>
                </div>
                <div class="workflow-card">
                    <div class="workflow-num">4</div>
                    <h3>Gemini Review</h3>
                    <p>Conducts multi-aspect review with structured JSON output.</p>
                </div>
                <div class="workflow-card">
                    <div class="workflow-num">5</div>
                    <h3>Post Review</h3>
                    <p>Submits summary comment & inline review lines.</p>
                </div>
            </div>
        </section>

        <footer class="footer">
            <p>Designed for portfolio exhibition. Uses LangGraph, FastAPI, and Google Gemini.</p>
            <p style="margin-top: 10px; font-size: 0.8rem; color: #4b5563;">&copy; 2026 AI-Powered Code Reviewer.</p>
        </footer>

    </body>
    </html>
    """
    return html_content
