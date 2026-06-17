import React, { useEffect } from "react";
import type { UiError } from "./errors";

type Props = {
  error: UiError | null;
  onClose: () => void;
};

export function ErrorPopup({ error, onClose }: Props) {
  useEffect(() => {
    if (!error) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [error, onClose]);

  if (!error) return null;

  const isExpenseCap = error.kind === "expense_cap";

  return (
    <div
      className="errorModalOverlay"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="error-modal-title"
      aria-describedby="error-modal-body"
      onClick={onClose}
    >
      <div
        className={`errorModal${isExpenseCap ? " errorModalExpense" : ""}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="errorModalTop">
          <div id="error-modal-title" className="errorModalTitle">
            {error.title}
          </div>
          <button className="btn secondary" type="button" onClick={onClose}>
            Close
          </button>
        </div>
        <p id="error-modal-body" className="errorModalBody">
          {error.message}
        </p>
        {isExpenseCap ? (
          <p className="errorModalHint muted">
            Catalog pricing and any results already on screen are still available. Generation will work again after
            quota resets.
          </p>
        ) : null}
        <div className="errorModalActions">
          <button className="btn primary" type="button" onClick={onClose}>
            OK
          </button>
        </div>
      </div>
    </div>
  );
}
