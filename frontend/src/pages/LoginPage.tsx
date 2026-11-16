import { useState, type FormEvent } from "react";
import { ApiError, errorMessage } from "../api/client";
import { FullPage } from "../components/States";
import { useSession } from "../session/SessionContext";

interface Errors {
  email?: string;
  password?: string;
  form?: string;
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function validate(email: string, password: string): Errors {
  const errors: Errors = {};
  if (!email.trim()) errors.email = "Enter your email address.";
  else if (!EMAIL_PATTERN.test(email.trim())) errors.email = "Enter a valid email address.";
  if (!password) errors.password = "Enter your password.";
  return errors;
}

export function LoginPage() {
  const { login } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const found = validate(email, password);
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    setSubmitting(true);
    try {
      await login(email.trim(), password);
      // On success the session state changes and the router leaves this page.
    } catch (error) {
      const fields = error instanceof ApiError ? error.fieldErrors : {};
      setErrors({
        email: fields.email?.[0],
        password: fields.password?.[0],
        form: fields.email || fields.password ? undefined : errorMessage(error),
      });
      setSubmitting(false);
    }
  }

  return (
    <FullPage>
      <form className="card auth-card" onSubmit={handleSubmit} noValidate>
        <h1 className="brand brand-large">MerchantFlow</h1>
        <p className="muted">Sign in to your workspace.</p>

        {errors.form && (
          <p className="alert" role="alert">
            {errors.form}
          </p>
        )}

        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            autoComplete="username"
            inputMode="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-invalid={Boolean(errors.email)}
            aria-describedby={errors.email ? "email-error" : undefined}
          />
          {errors.email && (
            <p id="email-error" className="field-error">
              {errors.email}
            </p>
          )}
        </div>

        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={Boolean(errors.password)}
            aria-describedby={errors.password ? "password-error" : undefined}
          />
          {errors.password && (
            <p id="password-error" className="field-error">
              {errors.password}
            </p>
          )}
        </div>

        <button type="submit" className="button button-primary" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </FullPage>
  );
}
