import { Component, type ReactNode } from 'react';

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <main className="fatal-screen">
      <p className="eyebrow">PROJECT PICASSO</p><h1>The studio needs a refresh.</h1>
      <p>Something interrupted the interface. No drawing or machine command was sent by this recovery action.</p>
      <button className="primary-button" onClick={() => window.location.reload()}>Reload studio</button>
    </main>;
    return this.props.children;
  }
}
