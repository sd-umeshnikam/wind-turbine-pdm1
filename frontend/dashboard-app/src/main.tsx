import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
// Global tokens/base styles first, so page stylesheets (imported via App) can override them.
import "./index.css";
import { App } from "./App";
import { applyAppearance, loadAppearance } from "./config/appearance";

// Before first render, so the saved theme/accent paints without a flash.
applyAppearance(loadAppearance());

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
