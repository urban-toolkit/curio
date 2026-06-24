(function webpackUniversalModuleDefinition(root, factory) {
	if(typeof exports === 'object' && typeof module === 'object')
		module.exports = factory(require("react"));
	else if(typeof define === 'function' && define.amd)
		define(["react"], factory);
	else if(typeof exports === 'object')
		exports["curio_softartifact_1"] = factory(require("react"));
	else
		root["curio_softartifact_1"] = factory(root["React"]);
})(this, (__WEBPACK_EXTERNAL_MODULE_react__) => {
return /******/ (() => { // webpackBootstrap
/******/ 	"use strict";
/******/ 	var __webpack_modules__ = ({

/***/ "../../../packages/curio.softartifact@1/sources/softArtifactBehavior.tsx"
/*!*******************************************************************************!*\
  !*** ../../../packages/curio.softartifact@1/sources/softArtifactBehavior.tsx ***!
  \*******************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   useSoftArtifactBehavior: () => (/* binding */ useSoftArtifactBehavior)
/* harmony export */ });
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! react */ "react");
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(react__WEBPACK_IMPORTED_MODULE_0__);
function _slicedToArray(r, e) { return _arrayWithHoles(r) || _iterableToArrayLimit(r, e) || _unsupportedIterableToArray(r, e) || _nonIterableRest(); }
function _nonIterableRest() { throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
function _iterableToArrayLimit(r, l) { var t = null == r ? null : "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (null != t) { var e, n, i, u, a = [], f = !0, o = !1; try { if (i = (t = t.call(r)).next, 0 === l) { if (Object(t) !== t) return; f = !1; } else for (; !(f = (e = i.call(t)).done) && (a.push(e.value), a.length !== l); f = !0); } catch (r) { o = !0, n = r; } finally { try { if (!f && null != t["return"] && (u = t["return"](), Object(u) !== u)) return; } finally { if (o) throw n; } } return a; } }
function _arrayWithHoles(r) { if (Array.isArray(r)) return r; }

function fakeIngest(file, role, nodeId) {
  return {
    artifactId: "saStub_".concat(nodeId, "_").concat(Date.now),
    fileName: file.name,
    artifactRole: role,
    status: 'ready'
  };
}

//todo: create a behavior hook for soft artifact behavior
var useSoftArtifactBehavior = function useSoftArtifactBehavior(data, nodeState) {
  var _useState = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)("inform"),
    _useState2 = _slicedToArray(_useState, 2),
    role = _useState2[0],
    setRole = _useState2[1];
  var _useState3 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState4 = _slicedToArray(_useState3, 2),
    file = _useState4[0],
    setFile = _useState4[1];
  var _useState5 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(false),
    _useState6 = _slicedToArray(_useState5, 2),
    busy = _useState6[0],
    setBusy = _useState6[1];
  var _useState7 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState8 = _slicedToArray(_useState7, 2),
    result = _useState8[0],
    setResult = _useState8[1];

  //call outputcallback when it is ingested, put in onIngest function
  var emitOutput = function emitOutput(descriptor) {
    var _data$outputCallback;
    var json = {
      dataType: 'dict',
      // JSON objects use 'dict' in Curio’s type system
      data: descriptor
    };
    nodeState.setOutput({
      code: 'success',
      content: JSON.stringify(json, null, 2),
      outputType: 'JSON'
    });
    (_data$outputCallback = data.outputCallback) === null || _data$outputCallback === void 0 || _data$outputCallback.call(data, data.nodeId, json);
  };

  //onChange function for ingest button 
  var onIngest = function onIngest() {
    if (!file) return;
    setBusy(true);
    setResult(null);

    //create a timeout to see ingest status
    window.setTimeout(function () {
      var out = fakeIngest(file, role, data.nodeId);
      setResult(out);
      emitOutput({
        artifactId: out.artifactId,
        fileName: out.fileName,
        artifactRole: out.artifactRole,
        status: out.status,
        stub: true
      });
      setBusy(false);
    }, 400);
  };
  var contentComponent = /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#64748b',
      marginBottom: 4
    }
  }, "Role:"), /*#__PURE__*/React.createElement("select", {
    value: role,
    onChange: function onChange(e) {
      return setRole(e.target.value);
    },
    style: {
      width: '100%',
      padding: '6px 8px'
    }
  }, /*#__PURE__*/React.createElement("option", {
    value: "inform"
  }, " inform "), /*#__PURE__*/React.createElement("option", {
    value: "explain"
  }, " explain "), /*#__PURE__*/React.createElement("option", {
    value: "transform"
  }, " transform "), /*#__PURE__*/React.createElement("option", {
    value: "expand"
  }, " expand ")), /*#__PURE__*/React.createElement("p", {
    style: {
      marginTop: 8,
      fontSize: 11
    }
  }, "Selected: ", role)), /*#__PURE__*/React.createElement("div", {
    style: {
      margin: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#64748b',
      marginBottom: 4
    }
  }, "Document:"), /*#__PURE__*/React.createElement("input", {
    type: "file",
    accept: ".pdf,.txt,.md",
    onChange: function onChange(e) {
      var _e$target$files$, _e$target$files;
      return setFile((_e$target$files$ = (_e$target$files = e.target.files) === null || _e$target$files === void 0 ? void 0 : _e$target$files[0]) !== null && _e$target$files$ !== void 0 ? _e$target$files$ : null);
    }
  }), file ? /*#__PURE__*/React.createElement("p", {
    style: {
      marginTop: 6,
      fontSize: 11
    }
  }, "Selected: ", file.name) : /*#__PURE__*/React.createElement("p", {
    style: {
      marginTop: 6,
      fontSize: 11,
      color: '#94a3b8'
    }
  }, "No file chosen")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: onIngest,
    disabled: !file || busy,
    style: {
      marginTop: 12,
      width: '100%',
      padding: '8px 12px',
      border: 'none',
      borderRadius: 8,
      fontWeight: 600,
      cursor: !file || busy ? 'not-allowed' : 'pointer',
      background: !file || busy ? '#e2e8f0' : '#2563eb',
      color: !file || busy ? '#94a3b8' : '#fff'
    }
  }, busy ? 'Ingesting…' : 'Ingest (stub)'), result ? /*#__PURE__*/React.createElement("pre", {
    style: {
      marginTop: 10,
      fontSize: 10,
      background: '#f8fafc',
      padding: 8
    }
  }, JSON.stringify(result, null, 2)) : null));
  return {
    contentComponent: contentComponent
  };
};

/***/ },

/***/ "react"
/*!**************************************************************************************!*\
  !*** external {"commonjs":"react","commonjs2":"react","amd":"react","root":"React"} ***!
  \**************************************************************************************/
(module) {

module.exports = __WEBPACK_EXTERNAL_MODULE_react__;

/***/ }

/******/ 	});
/************************************************************************/
/******/ 	// The module cache
/******/ 	var __webpack_module_cache__ = {};
/******/ 	
/******/ 	// The require function
/******/ 	function __webpack_require__(moduleId) {
/******/ 		// Check if module is in cache
/******/ 		var cachedModule = __webpack_module_cache__[moduleId];
/******/ 		if (cachedModule !== undefined) {
/******/ 			return cachedModule.exports;
/******/ 		}
/******/ 		// Create a new module (and put it into the cache)
/******/ 		var module = __webpack_module_cache__[moduleId] = {
/******/ 			// no module.id needed
/******/ 			// no module.loaded needed
/******/ 			exports: {}
/******/ 		};
/******/ 	
/******/ 		// Execute the module function
/******/ 		if (!(moduleId in __webpack_modules__)) {
/******/ 			delete __webpack_module_cache__[moduleId];
/******/ 			var e = new Error("Cannot find module '" + moduleId + "'");
/******/ 			e.code = 'MODULE_NOT_FOUND';
/******/ 			throw e;
/******/ 		}
/******/ 		__webpack_modules__[moduleId](module, module.exports, __webpack_require__);
/******/ 	
/******/ 		// Return the exports of the module
/******/ 		return module.exports;
/******/ 	}
/******/ 	
/************************************************************************/
/******/ 	/* webpack/runtime/compat get default export */
/******/ 	(() => {
/******/ 		// getDefaultExport function for compatibility with non-harmony modules
/******/ 		__webpack_require__.n = (module) => {
/******/ 			var getter = module && module.__esModule ?
/******/ 				() => (module['default']) :
/******/ 				() => (module);
/******/ 			__webpack_require__.d(getter, { a: getter });
/******/ 			return getter;
/******/ 		};
/******/ 	})();
/******/ 	
/******/ 	/* webpack/runtime/define property getters */
/******/ 	(() => {
/******/ 		// define getter functions for harmony exports
/******/ 		__webpack_require__.d = (exports, definition) => {
/******/ 			for(var key in definition) {
/******/ 				if(__webpack_require__.o(definition, key) && !__webpack_require__.o(exports, key)) {
/******/ 					Object.defineProperty(exports, key, { enumerable: true, get: definition[key] });
/******/ 				}
/******/ 			}
/******/ 		};
/******/ 	})();
/******/ 	
/******/ 	/* webpack/runtime/hasOwnProperty shorthand */
/******/ 	(() => {
/******/ 		__webpack_require__.o = (obj, prop) => (Object.prototype.hasOwnProperty.call(obj, prop))
/******/ 	})();
/******/ 	
/******/ 	/* webpack/runtime/make namespace object */
/******/ 	(() => {
/******/ 		// define __esModule on exports
/******/ 		__webpack_require__.r = (exports) => {
/******/ 			if(typeof Symbol !== 'undefined' && Symbol.toStringTag) {
/******/ 				Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' });
/******/ 			}
/******/ 			Object.defineProperty(exports, '__esModule', { value: true });
/******/ 		};
/******/ 	})();
/******/ 	
/************************************************************************/
var __webpack_exports__ = {};
// This entry needs to be wrapped in an IIFE because it needs to be isolated against other modules in the chunk.
(() => {
/*!****************************************************************!*\
  !*** ../../../packages/curio.softartifact@1/sources/index.tsx ***!
  \****************************************************************/
__webpack_require__.r(__webpack_exports__);
/* harmony import */ var _softArtifactBehavior__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! ./softArtifactBehavior */ "../../../packages/curio.softartifact@1/sources/softArtifactBehavior.tsx");

function registerAll(curio) {
  curio.registerBehavior('soft-artifact', _softArtifactBehavior__WEBPACK_IMPORTED_MODULE_0__.useSoftArtifactBehavior);
}
if (typeof window !== 'undefined') {
  var _w$curio, _w$__curioPendingPack;
  var w = window;
  if ((_w$curio = w.curio) !== null && _w$curio !== void 0 && _w$curio.registerBehavior) registerAll(w.curio);else ((_w$__curioPendingPack = w.__curioPendingPackages__) !== null && _w$__curioPendingPack !== void 0 ? _w$__curioPendingPack : w.__curioPendingPackages__ = []).push(registerAll);
}
})();

/******/ 	return __webpack_exports__;
/******/ })()
;
});
//# sourceMappingURL=behaviors.js.map