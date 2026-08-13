from agentic_portfolio_lab.dashboard import render_streamlit_dashboard
from agentic_portfolio_lab.dashboard_demo import build_demo_dashboard_view


def main() -> None:
    render_streamlit_dashboard(build_demo_dashboard_view())


if __name__ == "__main__":
    main()
