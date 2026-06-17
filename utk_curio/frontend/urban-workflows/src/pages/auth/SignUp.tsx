import React from "react";
import { Navigate } from "react-router-dom";
import { AuthFormWrapper } from "../../components/AuthForm/AuthFormWrapper";
import { SignUpForm } from "../../components/AuthForm/SignUpForm";
import { useUserContext } from "../../providers/UserProvider";

const SignUp: React.FC = () => {
  const { user, loading, enableUserAuth, skipProjectPage } = useUserContext();
  const entryRoute = skipProjectPage ? "/dataflow" : "/projects";

  if (!loading && (user || !enableUserAuth)) {
    return <Navigate to={entryRoute} replace />;
  }

  return (
    <AuthFormWrapper>
      <SignUpForm />
    </AuthFormWrapper>
  );
};

export default SignUp;
