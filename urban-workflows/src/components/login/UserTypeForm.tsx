import React, { useCallback, useState } from "react";
import CSS from "csstype";
import Container from "react-bootstrap/Container";
import { Button, ButtonGroup, Col, Row, ToggleButton } from "react-bootstrap";

import { useUserContext } from "../../providers/UserProvider";
import { useDialogContext } from "../../providers/DialogProvider";

export const UserTypeForm = () => {
  const { unsetDialog } = useDialogContext();
  const { saveUserType } = useUserContext();
  const [type, setType] = useState<"expert" | "programmer" | null>(null);

  const types = [
    { id: 1, name: "expert" },
    { id: 2, name: "programmer" },
  ];

  const handleSave = useCallback(async () => {
    if (!type) return;

    await saveUserType(type);
    unsetDialog();
  }, [type]);

  return (
    <div style={containerStyle} onClick={(e) => e.stopPropagation()}>
      <h1 style={titleStyle}>
        Welcome to out platform! <br />
        Now, inform which professional are you:
      </h1>
      <Container className="justify-content-md-center">
        <Row>
          <ButtonGroup>
            {types.map((currentType) => (
              <ToggleButton
                key={currentType.id}
                id={`radio-${currentType.id}`}
                type="radio"
                name="radio"
                value={currentType.name}
                variant="outline-primary"
                checked={type === currentType.name}
                onChange={(e) =>
                  setType(e.currentTarget.value as "programmer" | "expert")
                }
                style={{ margin: "10px", padding: "20px" }}
              >
                {currentType.name}
              </ToggleButton>
            ))}
          </ButtonGroup>
        </Row>

        <Row>
          <Button
            style={{
              width: "300px",
              margin: "50px auto 0 auto",
              padding: "20px",
            }}
            size="lg"
            disabled={!type}
            onClick={handleSave}
          >
            Save
          </Button>
        </Row>
      </Container>
    </div>
  );
};

const containerStyle: CSS.Properties = {
  width: "500px",
  maxWidth: "90%",
  height: "500px",
  display: "flex",
  flexDirection: "column",
  justifyContent: "center",
  alignItems: "center",
  backgroundColor: "white",
  padding: "10px",
};

const titleStyle: CSS.Properties = {
  fontWeight: "bold",
  marginBottom: "60px",
  textAlign: "center",
  fontSize: "1.8em",
};
