import { useState } from "react";

export function NoticeBanner({ notice, onDismiss }) {
  if (!notice) {
    return null;
  }

  return (
    <div className={`notice-banner notice-banner--${notice.tone || "info"}`}>
      <span>{notice.message}</span>
      <button type="button" className="notice-banner__dismiss" onClick={onDismiss}>
        Закрыть
      </button>
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  type = "button",
  disabled = false,
  className = "",
  ...props
}) {
  return (
    <button
      type={type}
      className={`button button--${variant} ${className}`.trim()}
      onClick={onClick}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  );
}

export function Panel({ eyebrow, title, description, actions, children, className = "" }) {
  return (
    <section className={`panel ${className}`.trim()}>
      {(eyebrow || title || description || actions) && (
        <header className="panel__header">
          <div>
            {eyebrow ? <p className="panel__eyebrow">{eyebrow}</p> : null}
            {title ? <h2 className="panel__title">{title}</h2> : null}
            {description ? <p className="panel__description">{description}</p> : null}
          </div>
          {actions ? <div className="panel__actions">{actions}</div> : null}
        </header>
      )}
      <div className="panel__body">{children}</div>
    </section>
  );
}

export function MetricCard({ label, value, tone = "teal" }) {
  return (
    <article className={`metric-card metric-card--${tone}`}>
      <p className="metric-card__label">{label}</p>
      <strong className="metric-card__value">{value}</strong>
    </article>
  );
}

export function Badge({ children, tone = "neutral" }) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}

export function EmptyState({ title, description, action }) {
  return (
    <div className="empty-state">
      <h3>{title}</h3>
      <p>{description}</p>
      {action ? <div className="empty-state__action">{action}</div> : null}
    </div>
  );
}

export function LoadingBlock({ label = "Загрузка..." }) {
  return (
    <div className="loading-block">
      <div className="loading-block__dot" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorBlock({ message, action }) {
  return (
    <div className="error-block">
      <strong>Не удалось загрузить данные.</strong>
      <p>{message}</p>
      {action ? <div className="error-block__action">{action}</div> : null}
    </div>
  );
}

export function TextField({
  label,
  value,
  onChange,
  placeholder = "",
  type = "text",
  required = false,
  help,
  revealable = false,
<<<<<<< ours
  onGenerate,
}) {
  const [revealed, setRevealed] = useState(false);
  const isPasswordField = type === "password";
  const hasPasswordActions = isPasswordField && (revealable || Boolean(onGenerate));
=======
}) {
  const [revealed, setRevealed] = useState(false);
  const isPasswordField = type === "password";
>>>>>>> theirs
  const inputType = isPasswordField && revealable && revealed ? "text" : type;

  return (
    <label className="form-field">
      <span>{label}</span>
<<<<<<< ours
      <div className={`form-field__input-wrap ${hasPasswordActions ? "form-field__input-wrap--password-actions" : ""}`.trim()}>
=======
      <div className={`form-field__input-wrap ${isPasswordField && revealable ? "form-field__input-wrap--revealable" : ""}`.trim()}>
>>>>>>> theirs
        <input
          type={inputType}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          required={required}
        />
<<<<<<< ours
        {hasPasswordActions ? (
          <div className="form-field__actions">
            {onGenerate ? (
              <button
                type="button"
                className="form-field__reveal"
                onClick={onGenerate}
                aria-label="Сгенерировать пароль"
              >
                Сгенерировать
              </button>
            ) : null}
            {isPasswordField && revealable ? (
              <button
                type="button"
                className="form-field__reveal"
                onClick={() => setRevealed((current) => !current)}
                aria-label={revealed ? "Скрыть пароль" : "Показать пароль"}
              >
                {revealed ? "Скрыть" : "Показать"}
              </button>
            ) : null}
          </div>
=======
        {isPasswordField && revealable ? (
          <button
            type="button"
            className="form-field__reveal"
            onClick={() => setRevealed((current) => !current)}
            aria-label={revealed ? "Скрыть пароль" : "Показать пароль"}
          >
            {revealed ? "Скрыть" : "Показать"}
          </button>
>>>>>>> theirs
        ) : null}
      </div>
      {help ? <small>{help}</small> : null}
    </label>
  );
}

export function TextAreaField({ label, value, onChange, rows = 4, placeholder = "" }) {
  return (
    <label className="form-field">
      <span>{label}</span>
      <textarea
        rows={rows}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
    </label>
  );
}

export function SelectField({ label, value, onChange, options, required = false }) {
  return (
    <label className="form-field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} required={required}>
        <option value="">Выберите вариант</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function Modal({ open, title, description, children, footer, onClose }) {
  if (!open) {
    return null;
  }

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div className="modal-card" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
        <header className="modal-card__header">
          <div>
            <h3>{title}</h3>
            {description ? <p>{description}</p> : null}
          </div>
          <button type="button" className="modal-card__close" onClick={onClose}>
            ×
          </button>
        </header>
        <div className="modal-card__body">{children}</div>
        {footer ? <footer className="modal-card__footer">{footer}</footer> : null}
      </div>
    </div>
  );
}
