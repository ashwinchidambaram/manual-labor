import { Component, type ErrorInfo, type ReactNode } from "react";

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };
  static getDerivedStateFromError(error: Error): State {
    return { error };
  }
  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("UI error", error, info.componentStack);
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="m-4 rounded-xl border border-fail-line bg-fail-wash p-4 text-ink" data-testid="error-boundary">
        <h2 className="font-semibold">Something went wrong on this screen</h2>
        <p className="text-sm">{this.state.error.message}</p>
        <button
          type="button"
          className="mt-2 min-h-[2.25rem] rounded-lg border border-line-strong bg-raised px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
          onClick={() => this.setState({ error: null })}
        >
          Try again
        </button>
      </div>
    );
  }
}
