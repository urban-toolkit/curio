import React from "react";
import { Navigate } from "react-router-dom";
import { AuthFormWrapper } from "../../components/AuthForm/AuthFormWrapper";
import { SignInForm } from "../../components/AuthForm/SignInForm";
import { useUserContext } from "../../providers/UserProvider";

const SignIn: React.FC = () => {
  const { user, loading, enableUserAuth, skipProjectPage } = useUserContext();
  const entryRoute = skipProjectPage ? "/dataflow" : "/projects";

  if (!loading && (user || !enableUserAuth)) {
    return <Navigate to={entryRoute} replace />;
  }

  return (
    <AuthFormWrapper>
      <SignInForm />
    </AuthFormWrapper>
  );
};

export default SignIn;
