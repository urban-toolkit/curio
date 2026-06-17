import React, { useState, FormEvent } from "react";
import CSS from "csstype";
import { useUserContext } from "../../providers/UserProvider";
import { AuthFormHeading } from "./AuthFormHeading";
import { AltAuthBox } from "./AltAuthBox";
import { useNavigate, Link } from "react-router-dom";

export const SignUpForm: React.FC = () => {
  const { signup, signinGuest, allowGuest, skipProjectPage } =
    useUserContext();
  const entryRoute = skipProjectPage ? "/dataflow" : "/projects";
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setSubmitting(true);
    try {
      await signup({
        name,
        username,
        password,
        email: email.trim() || undefined,
      });
      navigate(entryRoute);
    } catch (err: any) {
      setError(err.body?.error || err.message || "Sign up failed.");
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
        title="Create an account"
        subtitle="Fill in the details below to get started."
      />

      <form onSubmit={handleSubmit} style={formStyle}>
        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor="signup-name">Name</label>
          <input
            id="signup-name"
            style={inputStyle}
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoComplete="name"
            required
          />
        </div>

        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor="signup-username">Username</label>
          <input
            id="signup-username"
            style={inputStyle}
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            pattern="^[a-zA-Z0-9_]{3,32}$"
            title="3-32 characters: letters, digits, underscore"
            required
          />
        </div>

        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor="signup-email">Email (optional)</label>
          <input
            id="signup-email"
            style={inputStyle}
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
          />
        </div>

        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor="signup-password">Password</label>
          <input
            id="signup-password"
            style={inputStyle}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            autoComplete="new-password"
            required
          />
        </div>

        <div style={fieldGroupStyle}>
          <label style={labelStyle} htmlFor="signup-confirm-password">Confirm Password</label>
          <input
            id="signup-confirm-password"
            style={inputStyle}
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            autoComplete="new-password"
            required
          />
        </div>

        {error && <p style={errorStyle}>{error}</p>}

        <button type="submit" style={submitBtnStyle} disabled={submitting}>
          {submitting ? "Creating account..." : "Create Account"}
        </button>
      </form>

      <AltAuthBox showGuest={allowGuest} onGuest={handleGuest} />

      <p style={footerStyle}>
        Already have an account?{" "}
        <Link to="/auth/signin" style={linkStyle}>
          Sign in
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
  gap: "14px",
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
  height: "38px",
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
