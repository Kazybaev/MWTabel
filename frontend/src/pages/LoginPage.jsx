import { useState } from "react";

import { Button, TextField } from "../components/Ui";

export function LoginPage({ onLogin, loading, error }) {
  const [form, setForm] = useState({
    username: "",
    password: "",
  });

  async function handleSubmit(event) {
    event.preventDefault();
    await onLogin(form);
  }

  return (
    <div className="login-screen">
      <div className="login-screen__ambient login-screen__ambient--teal" aria-hidden="true" />
      <div className="login-screen__ambient login-screen__ambient--gold" aria-hidden="true" />
      <div className="login-screen__ambient login-screen__ambient--blue" aria-hidden="true" />
      <div className="login-screen__mesh" aria-hidden="true" />

      <div className="login-screen__content">
        <section className="login-hero">
          <p className="login-hero__eyebrow">MOTION WEB</p>
          <h1>Добро пожаловать в систему Tabel Motion Web</h1>
        </section>

        <section className="login-panel">
          <div className="login-panel__inner">
            <div className="login-panel__brand">
              <p className="panel__eyebrow">Вход</p>
              <h2>Войдите в систему</h2>
            </div>

            <form className="form-grid login-form" onSubmit={handleSubmit}>
              <TextField
                label="Логин"
                value={form.username}
                onChange={(value) => setForm((current) => ({ ...current, username: value }))}
                placeholder="Введите логин"
                required
              />
              <TextField
                label="Пароль"
                value={form.password}
                onChange={(value) => setForm((current) => ({ ...current, password: value }))}
                type="password"
                placeholder="Введите пароль"
                required
              />
              {error ? <p className="form-error">{error}</p> : null}
              <Button type="submit" disabled={loading} className="login-submit">
                {loading ? "Входим..." : "Войти"}
              </Button>
            </form>
          </div>
        </section>
      </div>
    </div>
  );
}
