"""Launch the NUMMF Dash interface."""

from cpse_harmonizer.dashboard.app import app

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8050)
