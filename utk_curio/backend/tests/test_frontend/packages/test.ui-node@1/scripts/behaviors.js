(function webpackUniversalModuleDefinition(root, factory) {
	if(typeof exports === 'object' && typeof module === 'object')
		module.exports = factory(require("react"));
	else if(typeof define === 'function' && define.amd)
		define(["react"], factory);
	else if(typeof exports === 'object')
		exports["test_ui-node_1"] = factory(require("react"));
	else
		root["test_ui-node_1"] = factory(root["React"]);
})(this, (__WEBPACK_EXTERNAL_MODULE_react__) => {
return /******/ (() => { // webpackBootstrap
/******/ 	"use strict";
/******/ 	var __webpack_modules__ = ({

/***/ "../../backend/tests/test_frontend/packages/test.ui-node@1/sources/uiNodeBehavior.tsx"
/*!********************************************************************************************!*\
  !*** ../../backend/tests/test_frontend/packages/test.ui-node@1/sources/uiNodeBehavior.tsx ***!
  \********************************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   useUiNodeBehavior: () => (/* binding */ useUiNodeBehavior)
/* harmony export */ });
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! react */ "react");
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(react__WEBPACK_IMPORTED_MODULE_0__);
var _curio2;
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _regenerator() { /*! regenerator-runtime -- Copyright (c) 2014-present, Facebook, Inc. -- license (MIT): https://github.com/babel/babel/blob/main/packages/babel-helpers/LICENSE */ var e, t, r = "function" == typeof Symbol ? Symbol : {}, n = r.iterator || "@@iterator", o = r.toStringTag || "@@toStringTag"; function i(r, n, o, i) { var c = n && n.prototype instanceof Generator ? n : Generator, u = Object.create(c.prototype); return _regeneratorDefine2(u, "_invoke", function (r, n, o) { var i, c, u, f = 0, p = o || [], y = !1, G = { p: 0, n: 0, v: e, a: d, f: d.bind(e, 4), d: function d(t, r) { return i = t, c = 0, u = e, G.n = r, a; } }; function d(r, n) { for (c = r, u = n, t = 0; !y && f && !o && t < p.length; t++) { var o, i = p[t], d = G.p, l = i[2]; r > 3 ? (o = l === n) && (u = i[(c = i[4]) ? 5 : (c = 3, 3)], i[4] = i[5] = e) : i[0] <= d && ((o = r < 2 && d < i[1]) ? (c = 0, G.v = n, G.n = i[1]) : d < l && (o = r < 3 || i[0] > n || n > l) && (i[4] = r, i[5] = n, G.n = l, c = 0)); } if (o || r > 1) return a; throw y = !0, n; } return function (o, p, l) { if (f > 1) throw TypeError("Generator is already running"); for (y && 1 === p && d(p, l), c = p, u = l; (t = c < 2 ? e : u) || !y;) { i || (c ? c < 3 ? (c > 1 && (G.n = -1), d(c, u)) : G.n = u : G.v = u); try { if (f = 2, i) { if (c || (o = "next"), t = i[o]) { if (!(t = t.call(i, u))) throw TypeError("iterator result is not an object"); if (!t.done) return t; u = t.value, c < 2 && (c = 0); } else 1 === c && (t = i["return"]) && t.call(i), c < 2 && (u = TypeError("The iterator does not provide a '" + o + "' method"), c = 1); i = e; } else if ((t = (y = G.n < 0) ? u : r.call(n, G)) !== a) break; } catch (t) { i = e, c = 1, u = t; } finally { f = 1; } } return { value: t, done: y }; }; }(r, o, i), !0), u; } var a = {}; function Generator() {} function GeneratorFunction() {} function GeneratorFunctionPrototype() {} t = Object.getPrototypeOf; var c = [][n] ? t(t([][n]())) : (_regeneratorDefine2(t = {}, n, function () { return this; }), t), u = GeneratorFunctionPrototype.prototype = Generator.prototype = Object.create(c); function f(e) { return Object.setPrototypeOf ? Object.setPrototypeOf(e, GeneratorFunctionPrototype) : (e.__proto__ = GeneratorFunctionPrototype, _regeneratorDefine2(e, o, "GeneratorFunction")), e.prototype = Object.create(u), e; } return GeneratorFunction.prototype = GeneratorFunctionPrototype, _regeneratorDefine2(u, "constructor", GeneratorFunctionPrototype), _regeneratorDefine2(GeneratorFunctionPrototype, "constructor", GeneratorFunction), GeneratorFunction.displayName = "GeneratorFunction", _regeneratorDefine2(GeneratorFunctionPrototype, o, "GeneratorFunction"), _regeneratorDefine2(u), _regeneratorDefine2(u, o, "Generator"), _regeneratorDefine2(u, n, function () { return this; }), _regeneratorDefine2(u, "toString", function () { return "[object Generator]"; }), (_regenerator = function _regenerator() { return { w: i, m: f }; })(); }
function _regeneratorDefine2(e, r, n, t) { var i = Object.defineProperty; try { i({}, "", {}); } catch (e) { i = 0; } _regeneratorDefine2 = function _regeneratorDefine(e, r, n, t) { function o(r, n) { _regeneratorDefine2(e, r, function (e) { return this._invoke(r, n, e); }); } r ? i ? i(e, r, { value: n, enumerable: !t, configurable: !t, writable: !t }) : e[r] = n : (o("next", 0), o("throw", 1), o("return", 2)); }, _regeneratorDefine2(e, r, n, t); }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: !0, configurable: !0, writable: !0 }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == _typeof(i) ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != _typeof(t) || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r || "default"); if ("object" != _typeof(i)) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
function _slicedToArray(r, e) { return _arrayWithHoles(r) || _iterableToArrayLimit(r, e) || _unsupportedIterableToArray(r, e) || _nonIterableRest(); }
function _nonIterableRest() { throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
function _iterableToArrayLimit(r, l) { var t = null == r ? null : "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (null != t) { var e, n, i, u, a = [], f = !0, o = !1; try { if (i = (t = t.call(r)).next, 0 === l) { if (Object(t) !== t) return; f = !1; } else for (; !(f = (e = i.call(t)).done) && (a.push(e.value), a.length !== l); f = !0); } catch (r) { o = !0, n = r; } finally { try { if (!f && null != t["return"] && (u = t["return"](), Object(u) !== u)) return; } finally { if (o) throw n; } } return a; } }
function _arrayWithHoles(r) { if (Array.isArray(r)) return r; }
function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
function asyncGeneratorStep(n, t, e, r, o, a, c) { try { var i = n[a](c), u = i.value; } catch (n) { return void e(n); } i.done ? t(u) : Promise.resolve(u).then(r, o); }
function _asyncToGenerator(n) { return function () { var t = this, e = arguments; return new Promise(function (r, o) { var a = n.apply(t, e); function _next(n) { asyncGeneratorStep(a, r, o, _next, _throw, "next", n); } function _throw(n) { asyncGeneratorStep(a, r, o, _next, _throw, "throw", n); } _next(void 0); }); }; }

/**
 * UI Node: a node with its own React interface.
 *
 * A behavior hook is a React custom hook. It receives the node's runtime
 * `data` and the shared `nodeState`, and returns the pieces of the node it
 * wants to override, here just `contentComponent`, the JSX rendered inside
 * the node body. All the normal rules of hooks apply.
 */

// Read an output with `window.curio.fetchData`, the function Curio's canvas
// reads outputs with: while a dataflow is open, on that dataflow's route, which
// also reads the outputs the dataflow saved, after a new sign-in too. Look it
// up on every read: your bundle can load before Curio publishes it.
function hostFetchData() {
  var _curio;
  var read = typeof window !== 'undefined' ? (_curio = window.curio) === null || _curio === void 0 ? void 0 : _curio.fetchData : undefined;
  return typeof read === 'function' ? read : null;
}

// For a host that does not publish `window.curio.fetchData`: read `/get` on
// the host's backend URL. Do NOT use `process.env.BACKEND_URL` here, which
// bakes your build machine's URL into the bundle you ship.
var BACKEND_URL = typeof window !== 'undefined' && ((_curio2 = window.curio) === null || _curio2 === void 0 ? void 0 : _curio2.backendUrl) || '';

/** The session token lives in a cookie; `/get` requires it. */
function sessionToken() {
  if (typeof document === 'undefined') return '';
  var hit = document.cookie.match(/(?:^|;\s*)session_token=([^;]*)/);
  return hit ? decodeURIComponent(hit[1]) : '';
}

// Keep rows as an output with `window.curio.storeOutput`, which answers the
// reference to hand on in their place, as every node hands on its output: a
// Python or JavaScript node reads only a stored output, and a save records
// only those. On a host that does not publish it, post them to `/storeOutput`.
function store(_x, _x2) {
  return _store.apply(this, arguments);
} // Payload shapes Curio recognises directly. Anything else is a generic
// envelope wrapped around one of these, so peel until we reach a known type.
function _store() {
  _store = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee2(nodeId, value) {
    var _curio3, _answer$output;
    var keep, token, res, answer;
    return _regenerator().w(function (_context2) {
      while (1) switch (_context2.n) {
        case 0:
          keep = typeof window !== 'undefined' ? (_curio3 = window.curio) === null || _curio3 === void 0 ? void 0 : _curio3.storeOutput : undefined;
          if (!(typeof keep === 'function')) {
            _context2.n = 1;
            break;
          }
          return _context2.a(2, keep(nodeId, value));
        case 1:
          token = sessionToken();
          _context2.n = 2;
          return fetch("".concat(BACKEND_URL, "/storeOutput"), {
            method: 'POST',
            headers: _objectSpread({
              'Content-Type': 'application/json'
            }, token ? {
              Authorization: "Bearer ".concat(token)
            } : {}),
            body: JSON.stringify({
              value: value
            })
          });
        case 2:
          res = _context2.v;
          _context2.n = 3;
          return res.json()["catch"](function () {
            return {};
          });
        case 3:
          answer = _context2.v;
          if (!(!res.ok || !(answer !== null && answer !== void 0 && (_answer$output = answer.output) !== null && _answer$output !== void 0 && _answer$output.path))) {
            _context2.n = 4;
            break;
          }
          throw new Error((answer === null || answer === void 0 ? void 0 : answer.error) || "Could not keep the output (HTTP ".concat(res.status, ")"));
        case 4:
          return _context2.a(2, answer.output);
      }
    }, _callee2);
  }));
  return _store.apply(this, arguments);
}
var KNOWN_TYPES = new Set(['dataframe', 'geodataframe', 'outputs']);
function unwrap(value) {
  var current = value;
  while (current && _typeof(current) === 'object' && typeof current.dataType === 'string' && !KNOWN_TYPES.has(current.dataType) && 'data' in current) {
    current = current.data;
  }
  return current;
}

/**
 * Turn whatever landed on `data.input` into real data.
 *
 * Upstream hands you one of two shapes, and a custom-UI node has to cope with
 * both:
 *
 *   { path: 'art-12', dataType: 'dataframe' }  a sandbox artifact reference,
 *                                              which is what every node
 *                                              produces -> read it with
 *                                              `window.curio.fetchData`
 *   { data: {...},    dataType: 'dataframe' }  an inline payload -> use it
 *                                              as-is
 */
function resolveInput(_x3) {
  return _resolveInput.apply(this, arguments);
}
/** A `dataframe` payload is column-oriented. Curio serialises with
 *  `to_dict(orient='list')`, so each column is an ARRAY; a hand-written
 *  spec may instead use a row map keyed by index. Accept both - a node
 *  that requires the row map sees no data at all from Curio (#194). */
function _resolveInput() {
  _resolveInput = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee3(input) {
    var _input$path;
    var ref, fetchData, token, res, _t2, _t3;
    return _regenerator().w(function (_context3) {
      while (1) switch (_context3.n) {
        case 0:
          if (!(input == null || input === '')) {
            _context3.n = 1;
            break;
          }
          return _context3.a(2, null);
        case 1:
          ref = typeof input === 'string' ? input : (_input$path = input.path) !== null && _input$path !== void 0 ? _input$path : input.dataset;
          if (!(typeof ref === 'string' && ref.trim())) {
            _context3.n = 7;
            break;
          }
          fetchData = hostFetchData();
          if (!fetchData) {
            _context3.n = 3;
            break;
          }
          _t2 = unwrap;
          _context3.n = 2;
          return fetchData(ref.trim());
        case 2:
          return _context3.a(2, _t2(_context3.v));
        case 3:
          token = sessionToken();
          _context3.n = 4;
          return fetch("".concat(BACKEND_URL, "/get?fileName=").concat(encodeURIComponent(ref.trim())), {
            headers: token ? {
              Authorization: "Bearer ".concat(token)
            } : {}
          });
        case 4:
          res = _context3.v;
          if (res.ok) {
            _context3.n = 5;
            break;
          }
          throw new Error("Could not read upstream data (HTTP ".concat(res.status, ")"));
        case 5:
          _t3 = unwrap;
          _context3.n = 6;
          return res.json();
        case 6:
          return _context3.a(2, _t3(_context3.v));
        case 7:
          return _context3.a(2, unwrap(input));
      }
    }, _callee3);
  }));
  return _resolveInput.apply(this, arguments);
}
function columnNames(payload) {
  var frame = (payload === null || payload === void 0 ? void 0 : payload.dataType) === 'dataframe' ? payload.data : payload;
  if (!frame || _typeof(frame) !== 'object') return [];
  return Object.keys(frame);
}
var useUiNodeBehavior = function useUiNodeBehavior(data, nodeState) {
  var _useState = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState2 = _slicedToArray(_useState, 2),
    payload = _useState2[0],
    setPayload = _useState2[1];
  var _useState3 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState4 = _slicedToArray(_useState3, 2),
    error = _useState4[0],
    setError = _useState4[1];
  var _useState5 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(''),
    _useState6 = _slicedToArray(_useState5, 2),
    column = _useState6[0],
    setColumn = _useState6[1];

  // Re-resolve whenever upstream produces something new.
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    var cancelled = false;
    setError(null);
    resolveInput(data.input).then(function (resolved) {
      if (cancelled) return;
      setPayload(resolved);
      var cols = columnNames(resolved);
      setColumn(function (prev) {
        var _cols$;
        return prev && cols.includes(prev) ? prev : (_cols$ = cols[0]) !== null && _cols$ !== void 0 ? _cols$ : '';
      });
    })["catch"](function (e) {
      if (!cancelled) setError(e.message || String(e));
    });
    return function () {
      cancelled = true;
    };
  }, [data.input]);
  var columns = columnNames(payload);

  // Push a result downstream: keep it, then hand on the reference. `dataType`
  // must match an output port type declared in manifest.json, lowercased.
  var emit = (0,react__WEBPACK_IMPORTED_MODULE_0__.useCallback)(/*#__PURE__*/_asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee() {
    var frame, stored, _t;
    return _regenerator().w(function (_context) {
      while (1) switch (_context.p = _context.n) {
        case 0:
          frame = (payload === null || payload === void 0 ? void 0 : payload.dataType) === 'dataframe' ? payload.data : payload;
          if (!(!frame || !column)) {
            _context.n = 1;
            break;
          }
          return _context.a(2);
        case 1:
          _context.p = 1;
          _context.n = 2;
          return store(data.nodeId, {
            data: _defineProperty({}, column, frame[column]),
            dataType: 'dataframe'
          });
        case 2:
          stored = _context.v;
          data.outputCallback(data.nodeId, stored);
          nodeState.setOutput({
            code: 'success',
            content: ''
          });
          _context.n = 4;
          break;
        case 3:
          _context.p = 3;
          _t = _context.v;
          nodeState.setOutput({
            code: 'error',
            content: _t.message || String(_t)
          });
        case 4:
          return _context.a(2);
      }
    }, _callee, null, [[1, 3]]);
  })), [payload, column, data, nodeState]);
  var contentComponent = /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      padding: 12,
      fontSize: 13,
      fontFamily: 'sans-serif',
      display: 'flex',
      flexDirection: 'column',
      gap: 8
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("strong", null, "UI Node"), error ? /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
    style: {
      color: '#c0392b'
    }
  }, error) : columns.length === 0 ? /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
    style: {
      color: '#888'
    }
  }, "Connect a DataFrame upstream and run it.") : /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement((react__WEBPACK_IMPORTED_MODULE_0___default().Fragment), null, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("label", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 4
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
    style: {
      color: '#666',
      fontSize: 11
    }
  }, "Column"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("select", {
    value: column,
    onChange: function onChange(e) {
      return setColumn(e.target.value);
    }
  }, columns.map(function (name) {
    return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("option", {
      key: name,
      value: name
    }, name);
  }))), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    type: "button",
    onClick: emit,
    disabled: !column
  }, "Send this column downstream")));
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
/*!***********************************************************************************!*\
  !*** ../../backend/tests/test_frontend/packages/test.ui-node@1/sources/index.tsx ***!
  \***********************************************************************************/
__webpack_require__.r(__webpack_exports__);
/* harmony import */ var _uiNodeBehavior__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! ./uiNodeBehavior */ "../../backend/tests/test_frontend/packages/test.ui-node@1/sources/uiNodeBehavior.tsx");
/**
 * Bundle entry point for this package.
 *
 * Webpack compiles this file into `../scripts/behaviors.js`. At boot Curio
 * fetches that bundle for every installed package whose manifest declares
 * `behaviorScript` and evaluates it, so the side effect below is what actually
 * registers the hook. The key passed to `registerBehavior` must match the
 * template's `behavior` field in manifest.json.
 *
 * React, ReactDOM and ReactFlow are externalised to `window` so this bundle
 * shares Curio's own instances: two copies of React break every hook.
 */


function registerAll(curio) {
  curio.registerBehavior('ui-node', _uiNodeBehavior__WEBPACK_IMPORTED_MODULE_0__.useUiNodeBehavior);
}
if (typeof window !== 'undefined') {
  var w = window;
  if (w.curio && typeof w.curio.registerBehavior === 'function') {
    registerAll(w.curio);
  } else {
    var _w$__curioPendingPack;
    // This bundle can load before Curio publishes its registry. Queue the
    // registration; the boot sequence drains the list once `window.curio` lands.
    var pending = (_w$__curioPendingPack = w.__curioPendingPackages__) !== null && _w$__curioPendingPack !== void 0 ? _w$__curioPendingPack : w.__curioPendingPackages__ = [];
    pending.push(registerAll);
  }
}
})();

/******/ 	return __webpack_exports__;
/******/ })()
;
});
//# sourceMappingURL=behaviors.js.map