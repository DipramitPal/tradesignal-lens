"""
Flask web application for the TradeSignal Lens budget advisor UI.

Launch via:  python main.py ui
"""

import os
import sys

# Ensure src/ is importable
_src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from flask import Flask, render_template, request, jsonify


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
    )

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/suggest", methods=["POST"])
    def suggest():
        data = request.get_json(silent=True) or {}
        try:
            budget = float(data.get("budget", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "Budget must be a number"}), 400

        risk_profile = data.get("risk_profile", "balanced")

        if budget < 500:
            return jsonify({"error": "Minimum budget is \u20b9500"}), 400
        if risk_profile not in ("conservative", "balanced", "aggressive"):
            return jsonify({"error": "Invalid risk profile"}), 400

        from portfolio.budget_advisor import BudgetAdvisor

        advisor = BudgetAdvisor()
        result = advisor.get_suggestions(budget, risk_profile)
        return jsonify(result)

    @app.route("/api/market-status")
    def market_status():
        from market_data.market_utils import market_status as get_status

        return jsonify(get_status())

    return app


if __name__ == "__main__":
    create_app().run(debug=True, host="0.0.0.0", port=5000)
