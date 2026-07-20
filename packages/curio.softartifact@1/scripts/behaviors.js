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
function _slicedToArray(r, e) { return _arrayWithHoles(r) || _iterableToArrayLimit(r, e) || _unsupportedIterableToArray(r, e) || _nonIterableRest(); }
function _nonIterableRest() { throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
function _iterableToArrayLimit(r, l) { var t = null == r ? null : "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (null != t) { var e, n, i, u, a = [], f = !0, o = !1; try { if (i = (t = t.call(r)).next, 0 === l) { if (Object(t) !== t) return; f = !1; } else for (; !(f = (e = i.call(t)).done) && (a.push(e.value), a.length !== l); f = !0); } catch (r) { o = !0, n = r; } finally { try { if (!f && null != t["return"] && (u = t["return"](), Object(u) !== u)) return; } finally { if (o) throw n; } } return a; } }
function _arrayWithHoles(r) { if (Array.isArray(r)) return r; }
function asyncGeneratorStep(n, t, e, r, o, a, c) { try { var i = n[a](c), u = i.value; } catch (n) { return void e(n); } i.done ? t(u) : Promise.resolve(u).then(r, o); }
function _asyncToGenerator(n) { return function () { var t = this, e = arguments; return new Promise(function (r, o) { var a = n.apply(t, e); function _next(n) { asyncGeneratorStep(a, r, o, _next, _throw, "next", n); } function _throw(n) { asyncGeneratorStep(a, r, o, _next, _throw, "throw", n); } _next(void 0); }); }; }
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: !0, configurable: !0, writable: !0 }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == _typeof(i) ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != _typeof(t) || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r || "default"); if ("object" != _typeof(i)) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }


// Reads the session token out of the browser's cookies (looks for a
// cookie named "session_token") so API calls can authenticate.
function getToken() {
  var match = document.cookie.match(/(?:^|;\s*)session_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : undefined;
}

// The different "modes" this artifact node can operate in — determines
// what happens to the uploaded document (just pass it through, explain it, etc.)

// Base URL for all softartifact API calls. Falls back to relative path
// if window.curio.backendUrl isn't set (e.g. during SSR or testing).
var API_BASE = "".concat(typeof window !== 'undefined' && ((_curio = window.curio) === null || _curio === void 0 ? void 0 : _curio.backendUrl) || '', "/api/softartifact");

// Shape of the persisted state for this node — this is what gets saved
// on the node data so it survives refreshes/reloads.

// Extends the generic NodeBehaviorData with this package's specific
// "softArtifact" field, since the base type doesn't know about it.

// Fresh/blank state for a node that has no artifact yet.
function defaultState() {
  return {
    artifactId: null,
    role: 'inform',
    sourceFile: null,
    mimeType: null,
    status: 'empty'
  };
}

// Restores state from whatever was previously saved on the node.
// Merges onto defaultState() so any missing/new fields still get
// sensible defaults (e.g. if the shape changed since last save).
function readSaved(data) {
  var raw = data.softArtifact;
  if (!raw || _typeof(raw) !== 'object') return defaultState(); //if raw is invalid return default state
  return _objectSpread(_objectSpread({}, defaultState()), raw);
}

// Produces the human-readable status label shown on the ingest button,
// based on current state and whether we're mid-verification.
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
      return "the state input is incorrect";
  }
}

// Calls the backend's /explain endpoint for a given artifact, asking it
// to summarize/explain the document (using the default query server-side).
function explainArtifact(_x, _x2) {
  return _explainArtifact.apply(this, arguments);
} // Call the backend's /inform endpoint for a given artifact
// to suggest new nodes or guidance using the given artifact 
function _explainArtifact() {
  _explainArtifact = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee6(artifactId, sourceFile) {
    var top_k,
      headers,
      token,
      res,
      err,
      _args6 = arguments;
    return _regenerator().w(function (_context6) {
      while (1) switch (_context6.n) {
        case 0:
          top_k = _args6.length > 2 && _args6[2] !== undefined ? _args6[2] : 8;
          headers = {
            'Content-Type': 'application/json'
          }; // Attach auth token if we have one
          token = getToken();
          if (token) {
            headers.Authorization = "Bearer ".concat(token);
          }
          _context6.n = 1;
          return fetch("".concat(API_BASE, "/explain"), {
            method: "POST",
            headers: headers,
            body: JSON.stringify({
              artifactId: artifactId,
              top_k: top_k,
              sourceFile: sourceFile
              //No query, use Default query
            })
          });
        case 1:
          res = _context6.v;
          if (res.ok) {
            _context6.n = 3;
            break;
          }
          _context6.n = 2;
          return res.json()["catch"](function () {
            return {};
          });
        case 2:
          err = _context6.v;
          throw new Error(err.error || err.hint || "HTTP ".concat(res.status));
        case 3:
          return _context6.a(2, res.json());
      }
    }, _callee6);
  }));
  return _explainArtifact.apply(this, arguments);
}
function informArtifact(_x3, _x4) {
  return _informArtifact.apply(this, arguments);
} // Call the backend's /propose_trill endpoint for a given artifact and context
// if context(dataflow) is none -> suggests a new dataflow
// if there is a context -> suggest edit to the dataflow 
function _informArtifact() {
  _informArtifact = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee7(artifactId, sourceFile) {
    var top_k,
      context,
      headers,
      token,
      body,
      res,
      err,
      _args7 = arguments;
    return _regenerator().w(function (_context7) {
      while (1) switch (_context7.n) {
        case 0:
          top_k = _args7.length > 2 && _args7[2] !== undefined ? _args7[2] : 8;
          context = _args7.length > 3 ? _args7[3] : undefined;
          headers = {
            'Content-Type': 'application/json'
          };
          token = getToken();
          if (token) {
            headers.Authorization = "Bearer ".concat(token);
          }
          body = {
            artifactId: artifactId,
            sourceFile: sourceFile,
            top_k: top_k
          };
          if (context !== undefined && context !== null && context !== '') {
            body.context = context;
          }
          _context7.n = 1;
          return fetch("".concat(API_BASE, "/inform"), {
            method: 'POST',
            headers: headers,
            body: JSON.stringify(body)
          });
        case 1:
          res = _context7.v;
          if (res.ok) {
            _context7.n = 3;
            break;
          }
          _context7.n = 2;
          return res.json()["catch"](function () {
            return {};
          });
        case 2:
          err = _context7.v;
          throw new Error(err.error || err.hint || "HTTP ".concat(res.status));
        case 3:
          return _context7.a(2, res.json());
      }
    }, _callee7);
  }));
  return _informArtifact.apply(this, arguments);
}
function proposeTrillArtifact(_x5, _x6) {
  return _proposeTrillArtifact.apply(this, arguments);
} // Main hook powering the "soft artifact" node's behavior — handles file
// upload/ingestion, state persistence, health checks, and the "explain" flow.
function _proposeTrillArtifact() {
  _proposeTrillArtifact = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee8(artifactId, sourceFile) {
    var top_k,
      role,
      context,
      headers,
      token,
      body,
      res,
      err,
      _args8 = arguments;
    return _regenerator().w(function (_context8) {
      while (1) switch (_context8.n) {
        case 0:
          top_k = _args8.length > 2 && _args8[2] !== undefined ? _args8[2] : 8;
          role = _args8.length > 3 ? _args8[3] : undefined;
          context = _args8.length > 4 ? _args8[4] : undefined;
          //create a json request
          //json request header
          headers = {
            "Content-Type": "application/json"
          };
          token = getToken();
          if (token) {
            headers.Authorization = "Bearer ".concat(token);
          }

          //json request body
          body = {
            artifactId: artifactId,
            sourceFile: sourceFile,
            top_k: top_k,
            role: role
          };
          if (context !== undefined && context !== null) {
            body.context = context;
          }

          //call API endpoint
          _context8.n = 1;
          return fetch("".concat(API_BASE, "/propose_trill"), {
            method: 'POST',
            headers: headers,
            body: JSON.stringify(body)
          });
        case 1:
          res = _context8.v;
          if (res.ok) {
            _context8.n = 3;
            break;
          }
          _context8.n = 2;
          return res.json()["catch"](function () {
            return {};
          });
        case 2:
          err = _context8.v;
          throw new Error(err.error || err.hint || "HTTP ".concat(res.status));
        case 3:
          return _context8.a(2, res.json());
      }
    }, _callee8);
  }));
  return _proposeTrillArtifact.apply(this, arguments);
}
var useSoftArtifactBehavior = function useSoftArtifactBehavior(data, nodeState) {
  var _state$proposal;
  //data doesn't have softArtifact field, therefore extending the package specific field for data (nodeData)
  var nodeData = data;
  var _useState = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(false),
    _useState2 = _slicedToArray(_useState, 2),
    backendUp = _useState2[0],
    setBackendUp = _useState2[1]; // is the backend reachable?
  var _useState3 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(function () {
      return readSaved(nodeData);
    }),
    _useState4 = _slicedToArray(_useState3, 2),
    state = _useState4[0],
    setState = _useState4[1]; // persisted artifact state
  var _useState5 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState6 = _slicedToArray(_useState5, 2),
    file = _useState6[0],
    setFile = _useState6[1]; // currently selected (not yet ingested) file
  var _useState7 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(false),
    _useState8 = _slicedToArray(_useState7, 2),
    verifying = _useState8[0],
    setVerifying = _useState8[1]; //short-lived UI while the GET api get run 
  var _useState9 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(false),
    _useState0 = _slicedToArray(_useState9, 2),
    explaining = _useState0[0],
    setExplaining = _useState0[1]; // true while /explain call is in flight
  var _useState1 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(false),
    _useState10 = _slicedToArray(_useState1, 2),
    informing = _useState10[0],
    setInforming = _useState10[1]; // true while /inform call is in flight
  var _useState11 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(false),
    _useState12 = _slicedToArray(_useState11, 2),
    proposing = _useState12[0],
    setProposing = _useState12[1];

  //health API call
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    var check = function check() {
      fetch("".concat(API_BASE, "/health")).then(function (response) {
        return setBackendUp(response.ok);
      })["catch"](function () {
        return setBackendUp(false);
      });
    };
    check(); // run immediately on mount
    var iv = setInterval(check, 60000); //check health every 60 seconds 
    return function () {
      return clearInterval(iv);
    }; // stop polling when unmounted
  }, []);

  //for the UI to survive after every refresh  
  // Updates both React state and the underlying node data object in one go,
  // so changes persist even if the component remounts/reloads.
  var persist = function persist(patch) {
    setState(function (prev) {
      var next = _objectSpread(_objectSpread({}, prev), patch);
      nodeData.softArtifact = next;
      return next;
    });
  };

  // Redundant safety net: whenever `state` changes for any reason, make sure
  // nodeData.softArtifact reflects it (in case persist() wasn't the source).
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    nodeData.softArtifact = state;
  }, [state]);

  //call outputcallback when it is ingested, put in onIngest function
  // Pushes this node's output downstream to connected nodes in the workflow,
  // wrapping the data in Curio's expected JSON output format.
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

  //persist + emitOutput
  // Called after a successful ingest: saves the returned artifact metadata
  // and forwards it as this node's output.
  var applyArtifactMeta = function applyArtifactMeta(out, role) {
    var _nodeData$softArtifac;
    persist({
      artifactId: typeof out.artifactId === 'string' ? out.artifactId : null,
      sourceFile: typeof out.sourceFile === 'string' ? out.sourceFile : null,
      mimeType: typeof out.mimeType === 'string' ? out.mimeType : null,
      status: 'ready',
      errorMessage: undefined
    });
    var cached = (_nodeData$softArtifac = nodeData.softArtifact) === null || _nodeData$softArtifac === void 0 ? void 0 : _nodeData$softArtifac.explanation;
    if (role === 'explain' && cached) {
      emitOutput(_objectSpread(_objectSpread({}, out), {}, {
        role: role,
        explanation: cached
      }));
    } else {
      emitOutput(_objectSpread(_objectSpread({}, out), {}, {
        role: role
      })); // downstream Simple View gets JSON again    
    }
  };

  // Runs the "explain" flow for the current artifact: calls the backend,
  // stores the explanation, and emits it as node output.
  var runExplain = /*#__PURE__*/function () {
    var _ref = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee(artifactId, role) {
      var out, _t;
      return _regenerator().w(function (_context) {
        while (1) switch (_context.p = _context.n) {
          case 0:
            if (!(role != 'explain' || !artifactId)) {
              _context.n = 1;
              break;
            }
            return _context.a(2);
          case 1:
            // only applies to the "explain" role

            setExplaining(true);
            _context.p = 2;
            _context.n = 3;
            return explainArtifact(artifactId, state.sourceFile);
          case 3:
            out = _context.v;
            persist({
              explanation: out.explanation
            });
            emitOutput({
              artifactId: artifactId,
              sourceFile: state.sourceFile,
              mimeType: state.mimeType,
              role: 'explain',
              explanation: out.explanation,
              query: out.query,
              spans: out.spans
            });
            _context.n = 5;
            break;
          case 4:
            _context.p = 4;
            _t = _context.v;
            // Surface any failure as node error state
            persist({
              status: 'error',
              errorMessage: _t instanceof Error ? _t.message : String(_t)
            });
          case 5:
            _context.p = 5;
            setExplaining(false);
            return _context.f(5);
          case 6:
            return _context.a(2);
        }
      }, _callee, null, [[2, 4, 5, 6]]);
    }));
    return function runExplain(_x7, _x8) {
      return _ref.apply(this, arguments);
    };
  }();

  // run 'Inform' flow for the current artifact, call the backend
  // emit the output
  var runInform = /*#__PURE__*/function () {
    var _ref2 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee2(artifactId, role) {
      var out, _t2;
      return _regenerator().w(function (_context2) {
        while (1) switch (_context2.p = _context2.n) {
          case 0:
            if (!(role != 'inform' || !artifactId)) {
              _context2.n = 1;
              break;
            }
            return _context2.a(2);
          case 1:
            setInforming(true);
            _context2.p = 2;
            _context2.n = 3;
            return informArtifact(artifactId, state.sourceFile);
          case 3:
            out = _context2.v;
            persist({
              guidance: out.guidance,
              suggestions: out.suggestions
            });
            emitOutput({
              artifactId: artifactId,
              sourceFile: state.sourceFile,
              mimeType: state.mimeType,
              role: 'inform',
              guidance: out.guidance,
              suggestions: out.suggestions
            });
            _context2.n = 5;
            break;
          case 4:
            _context2.p = 4;
            _t2 = _context2.v;
            persist({
              status: 'error',
              errorMessage: _t2 instanceof Error ? _t2.message : String(_t2)
            });
          case 5:
            _context2.p = 5;
            setInforming(false);
            return _context2.f(5);
          case 6:
            return _context2.a(2);
        }
      }, _callee2, null, [[2, 4, 5, 6]]);
    }));
    return function runInform(_x9, _x0) {
      return _ref2.apply(this, arguments);
    };
  }();

  // run propose, either it's transform or expand artifact
  // for now I haven't added context, need to add it  TODO
  var runPropose = /*#__PURE__*/function () {
    var _ref3 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee3(artifactId, role) {
      var context, out, _t3;
      return _regenerator().w(function (_context3) {
        while (1) switch (_context3.p = _context3.n) {
          case 0:
            if (!(role !== 'transform' && role !== 'expand')) {
              _context3.n = 1;
              break;
            }
            return _context3.a(2);
          case 1:
            setProposing(true);
            _context3.p = 2;
            context = typeof data.getCurrentTrill === "function" ? data.getCurrentTrill() : undefined;
            _context3.n = 3;
            return proposeTrillArtifact(artifactId, state.sourceFile, 8, role, context);
          case 3:
            out = _context3.v;
            persist({
              proposal: out.proposal,
              rationale: out.rationale
            });
            emitOutput({
              artifactId: artifactId,
              sourceFile: state.sourceFile,
              mimeType: state.mimeType,
              role: role,
              proposal: out.proposal,
              rationale: out.rationale
            });
            _context3.n = 5;
            break;
          case 4:
            _context3.p = 4;
            _t3 = _context3.v;
            persist({
              status: 'error',
              errorMessage: _t3 instanceof Error ? _t3.message : String(_t3)
            });
          case 5:
            _context3.p = 5;
            setProposing(false);
            return _context3.f(5);
          case 6:
            return _context3.a(2);
        }
      }, _callee3, null, [[2, 4, 5, 6]]);
    }));
    return function runPropose(_x1, _x10) {
      return _ref3.apply(this, arguments);
    };
  }();

  //on mount effect, run once when the node is reloaded
  // Verifies with the backend that a previously-saved artifactId still
  // exists (e.g. after a page refresh). If the backend no longer has it,
  // clears the stale state so the user knows to re-upload.
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    var _nodeData$softArtifac2;
    var artifactId = (_nodeData$softArtifac2 = nodeData.softArtifact) === null || _nodeData$softArtifac2 === void 0 ? void 0 : _nodeData$softArtifac2.artifactId;
    if (!artifactId) {
      // Nothing was previously ingested — nothing to verify, skip the GET
      console.log("soft artifact Id doesn't exist, skip GET");
      return;
    }
    console.log('[soft-artifact] mount: verifying', artifactId);
    // Guards against updating state after unmount (see earlier explanation)
    var cancelled = false;
    setVerifying(true);
    _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee4() {
      var _nodeData$softArtifac3, _nodeData$softArtifac4, res, out, role, _t4;
      return _regenerator().w(function (_context4) {
        while (1) switch (_context4.p = _context4.n) {
          case 0:
            _context4.p = 0;
            _context4.n = 1;
            return fetch("".concat(API_BASE, "/artifacts/").concat(encodeURI(artifactId)));
          case 1:
            res = _context4.v;
            if (!cancelled) {
              _context4.n = 2;
              break;
            }
            return _context4.a(2);
          case 2:
            if (!(res.status === 400)) {
              _context4.n = 3;
              break;
            }
            persist({
              artifactId: null,
              // clear stale id — backend doesn't have it
              sourceFile: null,
              // optional: clear or keep for context
              mimeType: null,
              status: 'error',
              errorMessage: 'artifact missing — re-upload',
              explanation: undefined
            });
            setFile(null);
            return _context4.a(2);
          case 3:
            if (res.ok) {
              _context4.n = 4;
              break;
            }
            return _context4.a(2);
          case 4:
            _context4.n = 5;
            return res.json();
          case 5:
            out = _context4.v;
            if (!cancelled) {
              _context4.n = 6;
              break;
            }
            return _context4.a(2);
          case 6:
            role = (_nodeData$softArtifac3 = (_nodeData$softArtifac4 = nodeData.softArtifact) === null || _nodeData$softArtifac4 === void 0 ? void 0 : _nodeData$softArtifac4.role) !== null && _nodeData$softArtifac3 !== void 0 ? _nodeData$softArtifac3 : state.role;
            applyArtifactMeta(out, role);
            _context4.n = 8;
            break;
          case 7:
            _context4.p = 7;
            _t4 = _context4.v;
            console.log("verifying unsuccesful with on mount effect softartifact node");
          case 8:
            _context4.p = 8;
            if (!cancelled) setVerifying(false);
            return _context4.f(8);
          case 9:
            return _context4.a(2);
        }
      }, _callee4, null, [[0, 7, 8, 9]]);
    }))();

    // Cleanup: mark this effect run as stale if the component unmounts
    return function () {
      cancelled = true;
    };
  }, []);

  //onChange function for ingest button 
  // Uploads the currently selected file to the backend for ingestion,
  // then applies the returned metadata and (if role is "explain") kicks
  // off the explain flow automatically.
  var onIngest = /*#__PURE__*/function () {
    var _ref5 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee5() {
      var _out$role, _out$role2, form, res, err, out, role, _t5;
      return _regenerator().w(function (_context5) {
        while (1) switch (_context5.p = _context5.n) {
          case 0:
            if (file) {
              _context5.n = 1;
              break;
            }
            return _context5.a(2);
          case 1:
            //before any fetch reset everything on the UI
            persist({
              artifactId: null,
              sourceFile: null,
              mimeType: null,
              status: 'ingesting',
              errorMessage: undefined,
              explanation: undefined,
              guidance: undefined,
              suggestions: undefined,
              proposal: undefined,
              rationale: undefined
            });
            //ingesting the using API_BASE/ingest 
            _context5.p = 2;
            form = new FormData();
            form.append('file', file);
            form.append('role', state.role);
            _context5.n = 3;
            return fetch("".concat(API_BASE, "/ingest"), {
              method: 'POST',
              headers: {},
              body: form
            });
          case 3:
            res = _context5.v;
            if (res.ok) {
              _context5.n = 5;
              break;
            }
            _context5.n = 4;
            return res.json()["catch"](function () {
              return {};
            });
          case 4:
            err = _context5.v;
            throw new Error(err.error || "HTTP  ".concat(res.status));
          case 5:
            _context5.n = 6;
            return res.json();
          case 6:
            out = _context5.v;
            role = (_out$role = out.role) !== null && _out$role !== void 0 ? _out$role : state.role;
            applyArtifactMeta(out, role);
            console.log('[soft-artifact] ingest out:', out);
            console.log('[soft-artifact] role:', (_out$role2 = out.role) !== null && _out$role2 !== void 0 ? _out$role2 : state.role, 'artifactId:', out.artifactId);
            // Automatically trigger explanation if this node's role is "explain"
            if (!(role === "explain" && out.artifactId)) {
              _context5.n = 7;
              break;
            }
            _context5.n = 7;
            return runExplain(out.artifactId, role);
          case 7:
            if (!(role === "inform" && out.artifactId)) {
              _context5.n = 8;
              break;
            }
            _context5.n = 8;
            return runInform(out.artifactId, role);
          case 8:
            if (!((role === "transform" || role === "expand") && out.artifactId)) {
              _context5.n = 9;
              break;
            }
            _context5.n = 9;
            return runPropose(out.artifactId, role);
          case 9:
            _context5.n = 11;
            break;
          case 10:
            _context5.p = 10;
            _t5 = _context5.v;
            persist({
              status: 'error',
              errorMessage: _t5 instanceof Error ? _t5.message : String(_t5)
            });
          case 11:
            return _context5.a(2);
        }
      }, _callee5, null, [[2, 10]]);
    }));
    return function onIngest() {
      return _ref5.apply(this, arguments);
    };
  }();

  // Handles selecting/clearing a file in the <input type="file">.
  // Doesn't upload anything yet — just updates local state until "ingest" is clicked.
  var onFile = function onFile(file) {
    setFile(file);
    if (!file) {
      // File cleared — reset artifact state entirely
      persist({
        artifactId: null,
        sourceFile: null,
        mimeType: null,
        status: 'empty',
        errorMessage: undefined,
        explanation: undefined,
        guidance: undefined,
        suggestions: undefined,
        proposal: undefined,
        rationale: undefined
      });
      return;
    }

    // New file selected — record its name/type but mark as not-yet-ingested
    persist({
      artifactId: null,
      sourceFile: file.name,
      mimeType: file.type || 'application/octet-stream',
      status: 'empty',
      errorMessage: undefined,
      explanation: undefined,
      guidance: undefined,
      suggestions: undefined,
      proposal: undefined,
      rationale: undefined
    });
  };

  // Handles changing the selected role (inform/explain/transform/expand)
  var onRole = function onRole(next) {
    persist({
      role: next
    });
  };

  // Display-only string reflecting backend health for the UI
  var statusText = backendUp ? "healthy backend" : "backend down";

  // ---- UI ----
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
  }, artifactStatusLine(state, verifying))), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", null, state.role === 'explain' && explaining ? /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("p", {
    style: {
      fontSize: 11,
      marginTop: 8
    }
  }, "Explaining\u2026") : null, state.explanation ? /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("pre", {
    style: {
      marginTop: 8,
      fontSize: 10,
      background: '#f8fafc',
      padding: 8,
      whiteSpace: 'pre-wrap'
    }
  }, state.explanation) : null), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", null, state.role === 'inform' && informing ? /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("p", {
    style: {
      fontSize: 11,
      marginTop: 8
    }
  }, "Informing\u2026") : null, state.guidance ? /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("pre", {
    style: {
      marginTop: 8,
      fontSize: 10,
      background: '#f8fafc',
      padding: 8,
      whiteSpace: 'pre-wrap'
    }
  }, state.guidance) : null, state.suggestions ? /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("pre", {
    style: {
      marginTop: 8,
      fontSize: 10,
      background: '#f8fafc',
      padding: 8,
      whiteSpace: 'pre-wrap'
    }
  }, JSON.stringify(state.suggestions, null, 2)) : null), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", null, state.role === 'transform' && proposing ? /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("p", {
    style: {
      fontSize: 11,
      marginTop: 8
    }
  }, "Transforming\u2026") : null, (_state$proposal = state.proposal) !== null && _state$proposal !== void 0 && _state$proposal.dataflow ? /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", null, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("p", null, state.rationale), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("p", null, "Review before applying"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    disabled: typeof data.applyProposal !== "function",
    onClick: function onClick() {
      var _data$applyProposal;
      (_data$applyProposal = data.applyProposal) === null || _data$applyProposal === void 0 || _data$applyProposal.call(data, state.proposal.dataflow);
    }
  }, "Apply proposal"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    onClick: function onClick() {
      var _data$cancelProposal;
      (_data$cancelProposal = data.cancelProposal) === null || _data$cancelProposal === void 0 || _data$cancelProposal.call(data);
      persist({
        proposal: undefined,
        rationale: undefined
      });
    }
  }, "Cancel"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("pre", {
    style: {
      marginTop: 8,
      fontSize: 10,
      background: '#f8fafc',
      padding: 8,
      whiteSpace: 'pre-wrap'
    }
  }, JSON.stringify(state.proposal, null, 2))) : null));
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