// If any part of the page crashes while drawing, show a polite message for THAT panel
// instead of a blank screen. The rest of the dashboard keeps working.

import { Component, type ReactNode } from "react";

export class ErrorBoundary extends Component<{ name: string; children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="m-4 rounded-md border border-critical/40 bg-critical/10 p-4 text-sm">
        <div className="font-medium text-up">The {this.props.name} could not be shown.</div>
        <div className="mt-1 text-ink-2">{this.state.error.message}</div>
        <button onClick={() => this.setState({ error: null })}
                className="mt-3 rounded-md border border-line px-2.5 py-1 text-xs hover:bg-raised">Try again</button>
      </div>
    );
  }
}
