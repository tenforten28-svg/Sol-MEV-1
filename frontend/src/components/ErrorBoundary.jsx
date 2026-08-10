import React from "react";

/**
 * ErrorBoundary — isolates one subtree from crashing the whole app.
 * Renders a compact red banner in place of the broken component.
 * The main use case that motivated this: a single panel rendering an object
 * as JSX (React error #31) was blanking the entire dashboard.
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, message: "" };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, message: error?.message?.slice(0, 260) || String(error).slice(0, 260) };
  }

  componentDidCatch(error, info) {
    console.error("[ErrorBoundary]", this.props.name || "unknown", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          data-testid={`error-boundary-${this.props.name || "panel"}`}
          className="my-4 rounded-md border border-red-500/50 bg-red-950/40 p-4 text-sm text-red-200"
        >
          <div className="font-semibold mb-1">
            Panel <span className="text-red-100">{this.props.name || "unknown"}</span> failed to render.
          </div>
          <div className="text-xs text-red-300 font-mono break-all">{this.state.message}</div>
          <button
            data-testid={`error-boundary-retry-${this.props.name || "panel"}`}
            onClick={() => this.setState({ hasError: false, message: "" })}
            className="mt-2 text-xs underline text-red-100 hover:text-white"
          >
            retry render
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
