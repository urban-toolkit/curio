/**
 * A rejected sign-in must leave the form standing, with what was typed and a
 * message saying why.
 *
 * The regression: `UserProvider` renders `{loading ? <Loading /> : children}`,
 * and `signin` used to hold `loading` true for the whole request. That unmounts
 * the very form awaiting the call, so a server rejection remounted a *fresh*
 * `SignInForm` — empty fields, and no error, because the `catch` that set it ran
 * on the instance that had just been thrown away. The user saw the form blink
 * and come back blank with nothing to explain it.
 *
 * The asymmetry that proves it is a bug rather than a design: both rejection
 * paths that return before the provider is reached (the HTML5 `minLength`
 * tooltip, and SignUpForm's "Passwords do not match." check) always kept their
 * fields and showed their message.
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const mockSignin = jest.fn();

jest.mock("../../utils/authApi", () => ({
  authApi: {
    getPublicConfig: jest.fn(() =>
      Promise.resolve({ enable_user_auth: true, allow_guest_login: true }),
    ),
    signin: (...args: unknown[]) => mockSignin(...args),
    signup: jest.fn(),
    signinGuest: jest.fn(),
    signinAutoGuest: jest.fn(),
    getMe: jest.fn(() => Promise.reject(new Error("no session"))),
    signout: jest.fn(),
  },
  getToken: () => null,
  setToken: jest.fn(),
  clearToken: jest.fn(),
}));

jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn(() => Promise.resolve()),
}));

import UserProvider from "../../providers/UserProvider";
import { SignInForm } from "../../components/AuthForm/SignInForm";

const renderSignIn = () =>
  render(
    <MemoryRouter>
      <UserProvider>
        <SignInForm />
      </UserProvider>
    </MemoryRouter>,
  );

describe("a rejected sign-in", () => {
  beforeEach(() => {
    mockSignin.mockReset();
  });

  it("keeps the typed username and shows the server's message", async () => {
    mockSignin.mockRejectedValue(
      Object.assign(new Error("Invalid credentials"), {
        body: { error: "Invalid credentials" },
      }),
    );
    renderSignIn();

    const identifier = await screen.findByLabelText("Username or Email");
    const password = screen.getByLabelText("Password");
    fireEvent.change(identifier, { target: { value: "robin_stress" } });
    fireEvent.change(password, { target: { value: "wrong-password" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await screen.findByText("Invalid credentials");

    // The form is the same instance: what was typed is still there.
    expect((identifier as HTMLInputElement).value).toBe("robin_stress");
  });

  it("does not swap the form out for the bootstrap spinner mid-request", async () => {
    let release: (reason: unknown) => void = () => {};
    mockSignin.mockImplementation(
      () => new Promise((_resolve, reject) => { release = reject; }),
    );
    renderSignIn();

    const identifier = await screen.findByLabelText("Username or Email");
    fireEvent.change(identifier, { target: { value: "robin_stress" } });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "wrong-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    // While the request is in flight the form must still be mounted — this is
    // the exact moment the old code replaced it with <Loading />.
    expect(screen.getByLabelText("Username or Email")).toBeInTheDocument();

    release(Object.assign(new Error("nope"), { body: { error: "nope" } }));
    await waitFor(() => expect(screen.getByText("nope")).toBeInTheDocument());
    expect(
      (screen.getByLabelText("Username or Email") as HTMLInputElement).value,
    ).toBe("robin_stress");
  });
});
