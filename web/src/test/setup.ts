import '@testing-library/jest-dom/vitest';

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({ matches: false, media: query, onchange: null,
    addListener: () => undefined, removeListener: () => undefined,
    addEventListener: () => undefined, removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
});
class ResizeObserverMock {
  observe() { /* browser layout is unavailable in jsdom */ }
  unobserve() { /* browser layout is unavailable in jsdom */ }
  disconnect() { /* browser layout is unavailable in jsdom */ }
}
globalThis.ResizeObserver = ResizeObserverMock;
window.scrollTo = () => undefined;
