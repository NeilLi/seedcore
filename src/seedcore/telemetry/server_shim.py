# Temporary shim: import the new app for backward compatibility
try:
    from .app import app
except Exception as e:
    # Fallback to old server if new app fails to import
    try:
        from .server import app
    except Exception as e2:
        # If relative imports fail, try absolute imports (when run directly)
        try:
            from src.seedcore.telemetry.app import app
        except Exception as e3:
            try:
                from src.seedcore.telemetry.server import app
            except Exception as e4:
                raise Exception(f"Failed to import new app: {e}. Failed to import old server: {e2}. Failed absolute import new app: {e3}. Failed absolute import old server: {e4}")

if __name__ == "__main__":
    import uvicorn, os
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8001")), reload=False)
