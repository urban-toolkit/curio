import React, { useCallback, useEffect, useState } from "react";
import CSS from "csstype";
import { Dropdown, Image, ToggleButton } from "react-bootstrap";

import { useUserContext } from "../../providers/UserProvider";
import { useDialogContext } from "../../providers/DialogProvider";
import { ProviderSignIn } from "./ProviderSignIn";

export const UserMenu = () => {
  const [show, setShow] = useState<boolean>(false);
  const { user, logout, saveUserType } = useUserContext();
  const { setDialog } = useDialogContext();
  const [type, setType] = useState<"expert" | "programmer" | null>(null);

  const handleSave = useCallback(
    async (newType: "expert" | "programmer") => {
      await saveUserType(newType);
      setType(newType);
    },
    [type]
  );

  useEffect(() => {
    if (user?.type) setType(user.type);
  }, [user?.type]);

  if (!user)
    return (
      <button
        style={buttonStyle}
        onClick={() => {
          setDialog(<ProviderSignIn />);
        }}
      >
        Login
      </button>
    );

  return (
    <div style={containerStyle}>
      <Dropdown show={show}>
        <Image
          src={user.profile_image}
          style={{ width: "50px" }}
          onClick={() => setShow((prevShow) => !prevShow)}
          roundedCircle
        />

        <Dropdown.Menu>
          <Dropdown.Item eventKey="1" onClick={logout}>
            Logout
          </Dropdown.Item>

          <p
            style={{
              width: "90%",
              margin: "20px auto 5px auto",
              fontWeight: "bold",
            }}
          >
            Choose a professional type
          </p>

          <Dropdown.Item eventKey="2">
            <ToggleButton
              id={`radio-1`}
              type="radio"
              name="radio"
              value={"programmer"}
              variant="outline-primary"
              checked={type === "programmer"}
              onClick={(e) => {
                handleSave("programmer");
              }}
              style={{ margin: "10px auto", padding: "20px", width: "100%" }}
              size="sm"
            >
              Programmer
            </ToggleButton>
          </Dropdown.Item>

          <Dropdown.Item eventKey="3">
            <ToggleButton
              id={`radio-2`}
              type="radio"
              name="radio"
              value={"expert"}
              variant="outline-primary"
              checked={type === "expert"}
              onClick={(e) => {
                handleSave("expert");
              }}
              style={{ margin: "10px auto", padding: "20px", width: "100%" }}
              size="sm"
            >
              Expert
            </ToggleButton>
          </Dropdown.Item>
        </Dropdown.Menu>
      </Dropdown>
    </div>
  );
};

const buttonStyle: CSS.Properties = {
  position: "fixed",
  top: "14px",
  right: "20px",
  border: "none",
  backgroundColor: "#fbfcf6",
  padding: "6px 10px",
  cursor: "pointer",
  borderRadius: "4px",
  fontWeight: "bold",
  color: "rgb(29, 56, 83)",
  zIndex: 200,
};

const containerStyle: CSS.Properties = {
  position: "fixed",
  top: "14px",
  right: "20px",
  display: "flex",
  cursor: "pointer",
  zIndex: 200,
};
