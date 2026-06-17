import React, { useState, FormEvent } from "react";
import CSS from "csstype";
import { useUserContext } from "../../providers/UserProvider";
import { AuthFormHeading } from "./AuthFormHeading";
import { AltAuthBox } from "./AltAuthBox";
import { useNavigate, Link } from "react-router-dom";

export const SignInForm: React.FC = () => {
  const { signin, signinGuest, allowGuest, skipProjectPage } =
    useUserContext();
  const entryRoute = skipProjectPage ? "/dataflow" : "/projects";
  const navigate = useNavigate();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await signin(identifier, password);
      navigate(entryRoute);
    } catch (err: any) {
      setError(err.body?.error || err.message || "Sign in failed.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleGuest = async () => {
    const user = await signinGuest();
    if (user) navigate(entryRoute);
  };

  return (
    <div style={formContainerStyle}>
      <AuthFormHeading
        title="Sign in"
        subtitle="Enter your username or email to continue."
      />

      <form onSubmit={handleSubmit} style={formStyle}>
        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor="signin-identifier">Username or Email</label>
          <input
            id="signin-identifier"
            style={inputStyle}
            type="text"
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            autoComplete="username"
            required
          />
        </div>

        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor="signin-password">Password</label>
          <input
            id="signin-password"
            style={inputStyle}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </div>

        {error && <p style={errorStyle}>{error}</p>}

        <button type="submit" style={submitBtnStyle} disabled={submitting}>
          {submitting ? "Signing in..." : "Sign In"}
        </button>
      </form>

      <AltAuthBox showGuest={allowGuest} onGuest={handleGuest} />

      <p style={footerStyle}>
        Don't have an account?{" "}
        <Link to="/auth/signup" style={linkStyle}>
          Create Account
        </Link>
      </p>
    </div>
  );
};

const formContainerStyle: CSS.Properties = {
  width: "100%",
  maxWidth: "400px",
};

const formStyle: CSS.Properties = {
  display: "flex",
  flexDirection: "column",
  gap: "16px",
};

const fieldGroupStyle: CSS.Properties = {
  display: "flex",
  flexDirection: "column",
  gap: "6px",
};

const labelStyle: CSS.Properties = {
  fontSize: "13px",
  fontWeight: 500,
  color: "#3A3A42",
};

const inputStyle: CSS.Properties = {
  height: "40px",
  padding: "0 12px",
  border: "1px solid #2A2A2E",
  borderRadius: "6px",
  fontSize: "14px",
  outline: "none",
  backgroundColor: "#fff",
};

const errorStyle: CSS.Properties = {
  color: "#D32F2F",
  fontSize: "13px",
  margin: 0,
};

const submitBtnStyle: CSS.Properties = {
  height: "42px",
  backgroundColor: "#1E1F23",
  color: "#fbfcf6",
  border: "none",
  borderRadius: "6px",
  fontSize: "14px",
  fontWeight: 600,
  cursor: "pointer",
};

const footerStyle: CSS.Properties = {
  fontSize: "13px",
  color: "#6B6B76",
  textAlign: "center",
  marginTop: "24px",
};

const linkStyle: CSS.Properties = {
  color: "#1E1F23",
  fontWeight: 600,
  textDecoration: "underline",
};
