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
var _curio;
function _regenerator() { /*! regenerator-runtime -- Copyright (c) 2014-present, Facebook, Inc. -- license (MIT): https://github.com/babel/babel/blob/main/packages/babel-helpers/LICENSE */ var e, t, r = "function" == typeof Symbol ? Symbol : {}, n = r.iterator || "@@iterator", o = r.toStringTag || "@@toStringTag"; function i(r, n, o, i) { var c = n && n.prototype instanceof Generator ? n : Generator, u = Object.create(c.prototype); return _regeneratorDefine2(u, "_invoke", function (r, n, o) { var i, c, u, f = 0, p = o || [], y = !1, G = { p: 0, n: 0, v: e, a: d, f: d.bind(e, 4), d: function d(t, r) { return i = t, c = 0, u = e, G.n = r, a; } }; function d(r, n) { for (c = r, u = n, t = 0; !y && f && !o && t < p.length; t++) { var o, i = p[t], d = G.p, l = i[2]; r > 3 ? (o = l === n) && (u = i[(c = i[4]) ? 5 : (c = 3, 3)], i[4] = i[5] = e) : i[0] <= d && ((o = r < 2 && d < i[1]) ? (c = 0, G.v = n, G.n = i[1]) : d < l && (o = r < 3 || i[0] > n || n > l) && (i[4] = r, i[5] = n, G.n = l, c = 0)); } if (o || r > 1) return a; throw y = !0, n; } return function (o, p, l) { if (f > 1) throw TypeError("Generator is already running"); for (y && 1 === p && d(p, l), c = p, u = l; (t = c < 2 ? e : u) || !y;) { i || (c ? c < 3 ? (c > 1 && (G.n = -1), d(c, u)) : G.n = u : G.v = u); try { if (f = 2, i) { if (c || (o = "next"), t = i[o]) { if (!(t = t.call(i, u))) throw TypeError("iterator result is not an object"); if (!t.done) return t; u = t.value, c < 2 && (c = 0); } else 1 === c && (t = i["return"]) && t.call(i), c < 2 && (u = TypeError("The iterator does not provide a '" + o + "' method"), c = 1); i = e; } else if ((t = (y = G.n < 0) ? u : r.call(n, G)) !== a) break; } catch (t) { i = e, c = 1, u = t; } finally { f = 1; } } return { value: t, done: y }; }; }(r, o, i), !0), u; } var a = {}; function Generator() {} function GeneratorFunction() {} function GeneratorFunctionPrototype() {} t = Object.getPrototypeOf; var c = [][n] ? t(t([][n]())) : (_regeneratorDefine2(t = {}, n, function () { return this; }), t), u = GeneratorFunctionPrototype.prototype = Generator.prototype = Object.create(c); function f(e) { return Object.setPrototypeOf ? Object.setPrototypeOf(e, GeneratorFunctionPrototype) : (e.__proto__ = GeneratorFunctionPrototype, _regeneratorDefine2(e, o, "GeneratorFunction")), e.prototype = Object.create(u), e; } return GeneratorFunction.prototype = GeneratorFunctionPrototype, _regeneratorDefine2(u, "constructor", GeneratorFunctionPrototype), _regeneratorDefine2(GeneratorFunctionPrototype, "constructor", GeneratorFunction), GeneratorFunction.displayName = "GeneratorFunction", _regeneratorDefine2(GeneratorFunctionPrototype, o, "GeneratorFunction"), _regeneratorDefine2(u), _regeneratorDefine2(u, o, "Generator"), _regeneratorDefine2(u, n, function () { return this; }), _regeneratorDefine2(u, "toString", function () { return "[object Generator]"; }), (_regenerator = function _regenerator() { return { w: i, m: f }; })(); }
function _regeneratorDefine2(e, r, n, t) { var i = Object.defineProperty; try { i({}, "", {}); } catch (e) { i = 0; } _regeneratorDefine2 = function _regeneratorDefine(e, r, n, t) { function o(r, n) { _regeneratorDefine2(e, r, function (e) { return this._invoke(r, n, e); }); } r ? i ? i(e, r, { value: n, enumerable: !t, configurable: !t, writable: !t }) : e[r] = n : (o("next", 0), o("throw", 1), o("return", 2)); }, _regeneratorDefine2(e, r, n, t); }
function asyncGeneratorStep(n, t, e, r, o, a, c) { try { var i = n[a](c), u = i.value; } catch (n) { return void e(n); } i.done ? t(u) : Promise.resolve(u).then(r, o); }
function _asyncToGenerator(n) { return function () { var t = this, e = arguments; return new Promise(function (r, o) { var a = n.apply(t, e); function _next(n) { asyncGeneratorStep(a, r, o, _next, _throw, "next", n); } function _throw(n) { asyncGeneratorStep(a, r, o, _next, _throw, "throw", n); } _next(void 0); }); }; }
function _slicedToArray(r, e) { return _arrayWithHoles(r) || _iterableToArrayLimit(r, e) || _unsupportedIterableToArray(r, e) || _nonIterableRest(); }
function _nonIterableRest() { throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
function _iterableToArrayLimit(r, l) { var t = null == r ? null : "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (null != t) { var e, n, i, u, a = [], f = !0, o = !1; try { if (i = (t = t.call(r)).next, 0 === l) { if (Object(t) !== t) return; f = !1; } else for (; !(f = (e = i.call(t)).done) && (a.push(e.value), a.length !== l); f = !0); } catch (r) { o = !0, n = r; } finally { try { if (!f && null != t["return"] && (u = t["return"](), Object(u) !== u)) return; } finally { if (o) throw n; } } return a; } }
function _arrayWithHoles(r) { if (Array.isArray(r)) return r; }
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: !0, configurable: !0, writable: !0 }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == _typeof(i) ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != _typeof(t) || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r || "default"); if ("object" != _typeof(i)) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }


//package specific field saved on node

function defaultState() {
  return {
    artifactId: null,
    role: 'inform',
    sourceFile: null,
    mimeType: null,
    status: 'empty'
  };
}
function readSaved(data) {
  var raw = data.softArtifact;
  if (!raw || _typeof(raw) !== 'object') return defaultState(); //if raw is invalid return default state
  return _objectSpread(_objectSpread({}, defaultState()), raw);
}
function artifactStatusLine(state, verifying) {
  var _state$errorMessage;
  if (verifying) return "verifying artifact";
  switch (state.status) {
    case 'empty':
      return state.sourceFile ? "File selected - not ingested" : "No Document here";
    case 'ingesting':
      return "ingesting";
    case 'ready':
      return "Ready";
    case 'error':
      return (_state$errorMessage = state.errorMessage) !== null && _state$errorMessage !== void 0 ? _state$errorMessage : "error";
    default:
      return "idk man";
  }
}
var API_BASE = "".concat(typeof window !== 'undefined' && ((_curio = window.curio) === null || _curio === void 0 ? void 0 : _curio.backendUrl) || '', "/api/softartifact");

//todo: create a behavior hook for soft artifact behavior
var useSoftArtifactBehavior = function useSoftArtifactBehavior(data, nodeState) {
  //health API
  var _useState = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(false),
    _useState2 = _slicedToArray(_useState, 2),
    backendUp = _useState2[0],
    setBackendUp = _useState2[1];
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    var check = function check() {
      fetch("".concat(API_BASE, "/health")).then(function (response) {
        return setBackendUp(response.ok);
      })["catch"](function () {
        return setBackendUp(false);
      });
    };
    check();
    var iv = setInterval(check, 10000); //check health every 10 seconds 
    return function () {
      return clearInterval(iv);
    };
  }, []);
  var _useState3 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState4 = _slicedToArray(_useState3, 2),
    file = _useState4[0],
    setFile = _useState4[1];

  //data doesn't have softArtifact field, therefore extending the package specific field for data (nodeData)
  var nodeData = data;
  var _useState5 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(function () {
      return readSaved(nodeData);
    }),
    _useState6 = _slicedToArray(_useState5, 2),
    state = _useState6[0],
    setState = _useState6[1];
  //for the UI to survive after every refresh  
  var persist = function persist(patch) {
    setState(function (prev) {
      var next = _objectSpread(_objectSpread({}, prev), patch);
      nodeData.softArtifact = next;
      return next;
    });
  };
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    nodeData.softArtifact = state;
  }, [state]);

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
  var applyArtifactMeta = function applyArtifactMeta(out, role) {
    persist({
      artifactId: typeof out.artifactId === 'string' ? out.artifactId : null,
      sourceFile: typeof out.sourceFile === 'string' ? out.sourceFile : null,
      mimeType: typeof out.mimeType === 'string' ? out.mimeType : null,
      status: 'ready',
      errorMessage: undefined
    });
    emitOutput(_objectSpread(_objectSpread({}, out), {}, {
      role: role
    })); // downstream Simple View gets JSON again
  };
  var _useState7 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(false),
    _useState8 = _slicedToArray(_useState7, 2),
    verifying = _useState8[0],
    setVerifying = _useState8[1]; //short-lived UI while the GET api get run 
  //on mount effect, run once when the node is reloaded 
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    var _nodeData$softArtifac;
    var artifactId = (_nodeData$softArtifac = nodeData.softArtifact) === null || _nodeData$softArtifac === void 0 ? void 0 : _nodeData$softArtifac.artifactId;
    if (!artifactId) {
      console.log("soft artifact Id doesn't exist, skip GET");
      return;
    }
    console.log('[soft-artifact] mount: verifying', artifactId);
    var cancelled = false;
    setVerifying(true);
    _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee() {
      var _nodeData$softArtifac2, _nodeData$softArtifac3, res, out, role, _t;
      return _regenerator().w(function (_context) {
        while (1) switch (_context.p = _context.n) {
          case 0:
            _context.p = 0;
            _context.n = 1;
            return fetch("".concat(API_BASE, "/artifacts/").concat(encodeURI(artifactId)));
          case 1:
            res = _context.v;
            if (!cancelled) {
              _context.n = 2;
              break;
            }
            return _context.a(2);
          case 2:
            if (!(res.status === 400)) {
              _context.n = 3;
              break;
            }
            persist({
              artifactId: null,
              // clear stale id — backend doesn't have it
              sourceFile: null,
              // optional: clear or keep for context
              mimeType: null,
              status: 'error',
              errorMessage: 'artifact missing — re-upload'
            });
            setFile(null);
            return _context.a(2);
          case 3:
            if (res.ok) {
              _context.n = 4;
              break;
            }
            return _context.a(2);
          case 4:
            _context.n = 5;
            return res.json();
          case 5:
            out = _context.v;
            if (!cancelled) {
              _context.n = 6;
              break;
            }
            return _context.a(2);
          case 6:
            role = (_nodeData$softArtifac2 = (_nodeData$softArtifac3 = nodeData.softArtifact) === null || _nodeData$softArtifac3 === void 0 ? void 0 : _nodeData$softArtifac3.role) !== null && _nodeData$softArtifac2 !== void 0 ? _nodeData$softArtifac2 : state.role;
            applyArtifactMeta(out, role);
            _context.n = 8;
            break;
          case 7:
            _context.p = 7;
            _t = _context.v;
            console.log("ERROR HERE I LOVE FREEDOM");
          case 8:
            _context.p = 8;
            if (!cancelled) setVerifying(false);
            return _context.f(8);
          case 9:
            return _context.a(2);
        }
      }, _callee, null, [[0, 7, 8, 9]]);
    }))();
    return function () {
      cancelled = true;
    };
  }, []);

  //onChange function for ingest button 
  var onIngest = /*#__PURE__*/function () {
    var _ref2 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee2() {
      var _out$role, form, res, err, out, _t2;
      return _regenerator().w(function (_context2) {
        while (1) switch (_context2.p = _context2.n) {
          case 0:
            if (file) {
              _context2.n = 1;
              break;
            }
            return _context2.a(2);
          case 1:
            persist({
              status: "ingesting"
            });

            //ingesting the using API_BASE/ingest 
            _context2.p = 2;
            form = new FormData();
            form.append('file', file);
            form.append('role', state.role);
            _context2.n = 3;
            return fetch("".concat(API_BASE, "/ingest"), {
              method: 'POST',
              headers: {},
              body: form
            });
          case 3:
            res = _context2.v;
            if (res.ok) {
              _context2.n = 5;
              break;
            }
            _context2.n = 4;
            return res.json()["catch"](function () {
              return {};
            });
          case 4:
            err = _context2.v;
            throw new Error(err.error || "HTTP  ".concat(res.status));
          case 5:
            _context2.n = 6;
            return res.json();
          case 6:
            out = _context2.v;
            applyArtifactMeta(out, (_out$role = out.role) !== null && _out$role !== void 0 ? _out$role : state.role);
            _context2.n = 8;
            break;
          case 7:
            _context2.p = 7;
            _t2 = _context2.v;
            persist({
              status: 'error',
              errorMessage: _t2 instanceof Error ? _t2.message : String(_t2)
            });
          case 8:
            return _context2.a(2);
        }
      }, _callee2, null, [[2, 7]]);
    }));
    return function onIngest() {
      return _ref2.apply(this, arguments);
    };
  }();
  var onFile = function onFile(file) {
    setFile(file);
    if (!file) {
      persist({
        artifactId: null,
        sourceFile: null,
        mimeType: null,
        status: 'empty',
        errorMessage: undefined
      });
      return;
    }
    persist({
      artifactId: null,
      sourceFile: file.name,
      mimeType: file.type || 'application/octet-stream',
      status: 'empty'
    });
  };
  var onRole = function onRole(next) {
    persist({
      role: next
    });
  };
  var statusText = backendUp ? "healthy af" : "sad af";
  var contentComponent = /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement((react__WEBPACK_IMPORTED_MODULE_0___default().Fragment), null, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", null, "backends are ", statusText), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      padding: 12
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#64748b',
      marginBottom: 4
    }
  }, "Role:"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("select", {
    value: state.role,
    onChange: function onChange(e) {
      return onRole(e.target.value);
    },
    style: {
      width: '100%',
      padding: '6px 8px'
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("option", {
    value: "inform"
  }, " inform "), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("option", {
    value: "explain"
  }, " explain "), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("option", {
    value: "transform"
  }, " transform "), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("option", {
    value: "expand"
  }, " expand ")), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("p", {
    style: {
      marginTop: 8,
      fontSize: 11
    }
  }, "Selected: ", state.role)), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      margin: 10
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#64748b',
      marginBottom: 4
    }
  }, "Document:"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("input", {
    type: "file",
    accept: ".pdf,.txt,.md",
    onChange: function onChange(e) {
      var _e$target$files$, _e$target$files;
      return onFile((_e$target$files$ = (_e$target$files = e.target.files) === null || _e$target$files === void 0 ? void 0 : _e$target$files[0]) !== null && _e$target$files$ !== void 0 ? _e$target$files$ : null);
    }
  }), state.sourceFile ? /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("p", {
    style: {
      marginTop: 6,
      fontSize: 11
    }
  }, "Selected: ", state.sourceFile) : /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("p", {
    style: {
      marginTop: 6,
      fontSize: 11,
      color: '#94a3b8'
    }
  }, "No file chosen")), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", null, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    type: "button",
    onClick: onIngest,
    disabled: !file || state.status === 'ingesting' || !backendUp,
    style: {
      marginTop: 10,
      width: '50%',
      padding: '8px 12px',
      border: 'none',
      borderRadius: 5,
      fontWeight: 400,
      cursor: !file || state.status === 'ingesting' ? 'not-allowed' : 'pointer',
      background: !file || state.status === 'ingesting' ? '#e2e8f0' : '#2563eb',
      color: !file || state.status === 'ingesting' ? '#94a3b8' : '#fff'
    }
  }, artifactStatusLine(state, verifying)), state ? /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("pre", {
    style: {
      marginTop: 10,
      fontSize: 10,
      background: '#f8fafc',
      padding: 8
    }
  }, JSON.stringify(state, null, 2)) : null));
  return {
    contentComponent: contentComponent,
    disablePlay: true
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