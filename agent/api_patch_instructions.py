"""
PATCH FOR agent/api.py
─────────────────────────────────────────────────────────────────────────────
This file shows what to add to your existing api.py.

DO NOT replace the whole file — just add these snippets in the right places.
"""

# ════════════════════════════════════════════════════════════════════════════
# 1) ADD IMPORTS at the top of api.py (after existing imports)
# ════════════════════════════════════════════════════════════════════════════
"""
import asyncio
from contextlib import asynccontextmanager

from agent.auth_routes  import router as auth_router
from agent.email_monitor import monitor_loop, stop as stop_monitor
"""

# ════════════════════════════════════════════════════════════════════════════
# 2) ADD LIFESPAN MANAGER above your `app = FastAPI(...)` line
# ════════════════════════════════════════════════════════════════════════════
"""
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    monitor_task = asyncio.create_task(monitor_loop())
    log.info("[api] Email monitor started")
    yield
    # Shutdown
    stop_monitor()
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass
    log.info("[api] Email monitor stopped")
"""

# ════════════════════════════════════════════════════════════════════════════
# 3) UPDATE app = FastAPI(...) to include lifespan
# ════════════════════════════════════════════════════════════════════════════
"""
app = FastAPI(
    title="SentryPay API",
    version="1.0.0",
    lifespan=lifespan,                # ← ADD THIS LINE
)
"""

# ════════════════════════════════════════════════════════════════════════════
# 4) MOUNT THE AUTH ROUTER (after CORS middleware setup)
# ════════════════════════════════════════════════════════════════════════════
"""
app.include_router(auth_router)
"""

# ════════════════════════════════════════════════════════════════════════════
# 5) UPDATE CORS to allow Authorization header
#    (your existing CORSMiddleware should already include "Authorization")
# ════════════════════════════════════════════════════════════════════════════
"""
app.add_middleware(
    CORSMiddleware,
    allow_origins   = ALLOWED_ORIGINS,
    allow_credentials = True,
    allow_methods   = ["GET", "POST", "OPTIONS"],
    allow_headers   = ["*", "Authorization", "X-API-Key"],   # ensure Authorization is here
)
"""