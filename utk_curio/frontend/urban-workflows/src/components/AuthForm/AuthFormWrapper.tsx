import React, { ReactNode } from "react";
import CSS from "csstype";
import curioLogoWhite from "assets/curio_logo_white.png";
import urbaniteLogo from "assets/urbanite.png";
import scoutLogo from "assets/scout.png";
import autarkLogo from "assets/autark.png";
import utkLogo from "assets/utk.png";
import evlLogo from "assets/evl.png";
import uicLogo from "assets/uic.png";

interface Props {
  children: ReactNode;
}

const siblingLogos = [
  // A sibling research project, not a Curio feature. The Urbanite *feature*
  // was folded into the Agent Catalog; this credit stays.
  { src: urbaniteLogo, alt: "Urbanite", href: "https://urbantk.org/urbanite", label: "urbantk.org/urbanite", filter: "grayscale(1)" },
  { src: scoutLogo,    alt: "Scout",    href: "https://urbantk.org/scout",    label: "urbantk.org/scout",    filter: "grayscale(1)" },
  { src: autarkLogo,   alt: "Autark",   href: "https://autarkjs.org",          label: "autarkjs.org",          filter: "brightness(0) invert(1)" },
];

const footerLogos = [
  { src: utkLogo, alt: "UrbanTK", href: "https://urbantk.org",      filter: undefined },
  { src: evlLogo, alt: "EVL",     href: "https://www.evl.uic.edu",  filter: "brightness(0) invert(1)" },
  { src: uicLogo, alt: "UIC",     href: "https://www.uic.edu",      filter: "brightness(0) invert(1)" },
];

export const AuthFormWrapper: React.FC<Props> = ({ children }) => {
  return (
    <div style={outerStyle}>
      <div style={leftPanelStyle}>
        <div style={centerContentStyle}>
          <a href="https://urbantk.org/curio" target="_blank" rel="noreferrer" style={{ display: "block", textAlign: "center" }}>
            <img src={curioLogoWhite} alt="Curio" style={logoStyle} />
          </a>
          <div style={taglineGroupStyle}>
            <p style={taglineStyle}>Visual dataflows for urban data</p>
            <a href="https://urbantk.org/curio" target="_blank" rel="noreferrer" style={urlStyle}>
              urbantk.org/curio
            </a>
          </div>
          <div style={siblingRowStyle}>
            {siblingLogos.map(({ src, alt, href, label, filter }) => (
              <a key={alt} href={href} target="_blank" rel="noreferrer" style={siblingItemStyle}>
                <img src={src} alt={alt} style={{ ...siblingLogoStyle, filter }} />
                <span style={siblingUrlStyle}>{label}</span>
              </a>
            ))}
          </div>
        </div>
        <div style={footerStyle}>
          <div style={footerLogosRowStyle}>
            {footerLogos.map(({ src, alt, href, filter }) =>
              href ? (
                <a key={alt} href={href} target="_blank" rel="noreferrer">
                  <img src={src} alt={alt} style={{ ...footerLogoStyle, filter }} />
                </a>
              ) : (
                <img key={alt} src={src} alt={alt} style={{ ...footerLogoStyle, filter }} />
              )
            )}
          </div>
          <p style={nsfTextStyle}>
            Supported with funding from the National Science Foundation (NSF)
            <br />
            Awards #2320261, #2330565, and #2411223
          </p>
        </div>
      </div>
      <div style={rightPanelStyle}>{children}</div>
    </div>
  );
};

const outerStyle: CSS.Properties = {
  display: "flex",
  minHeight: "100vh",
  fontFamily:
    "Rubik, -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif",
};

const leftPanelStyle: CSS.Properties = {
  width: "42%",
  backgroundColor: "#1E1F23",
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "space-between",
  padding: "40px",
};

const centerContentStyle: CSS.Properties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  gap: "28px",
  flex: 1,
  justifyContent: "center",
};

const logoStyle: CSS.Properties = {
  width: "60%",
  maxWidth: "340px",
  height: "auto",
};

const taglineGroupStyle: CSS.Properties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  gap: "8px",
};

const taglineStyle: CSS.Properties = {
  color: "#D8D8D8",
  fontSize: "17px",
  fontWeight: 400,
  letterSpacing: "1px",
  margin: 0,
  textAlign: "center",
};

const urlStyle: CSS.Properties = {
  color: "#888",
  fontSize: "13px",
  textDecoration: "none",
  letterSpacing: "0.5px",
};

const rightPanelStyle: CSS.Properties = {
  width: "58%",
  backgroundColor: "#f0f0f0",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: "40px",
};

const siblingRowStyle: CSS.Properties = {
  display: "flex",
  flexDirection: "row",
  gap: "24px",
  alignItems: "flex-start",
  justifyContent: "center",
};

const siblingItemStyle: CSS.Properties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  gap: "6px",
  textDecoration: "none",
};

const siblingLogoStyle: CSS.Properties = {
  width: "72px",
  height: "auto",
};

const siblingUrlStyle: CSS.Properties = {
  color: "#888",
  fontSize: "11px",
  letterSpacing: "0.3px",
  textAlign: "center",
};

const footerStyle: CSS.Properties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  gap: "12px",
  paddingTop: "24px",
  borderTop: "1px solid #333",
  width: "100%",
};

const footerLogosRowStyle: CSS.Properties = {
  display: "flex",
  flexDirection: "row",
  gap: "24px",
  alignItems: "center",
  justifyContent: "center",
};

const footerLogoStyle: CSS.Properties = {
  height: "36px",
  width: "auto",
  filter: "brightness(0) invert(1)",
};

const nsfTextStyle: CSS.Properties = {
  color: "#888",
  fontSize: "11px",
  textAlign: "center",
  margin: 0,
  lineHeight: "1.6",
  letterSpacing: "0.3px",
};
