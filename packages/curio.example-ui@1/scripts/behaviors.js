(function webpackUniversalModuleDefinition(root, factory) {
	if(typeof exports === 'object' && typeof module === 'object')
		module.exports = factory(require("react"));
	else if(typeof define === 'function' && define.amd)
		define(["react"], factory);
	else if(typeof exports === 'object')
		exports["curio_example-ui_1"] = factory(require("react"));
	else
		root["curio_example-ui_1"] = factory(root["React"]);
})(this, (__WEBPACK_EXTERNAL_MODULE_react__) => {
return /******/ (() => { // webpackBootstrap
/******/ 	"use strict";
/******/ 	var __webpack_modules__ = ({

/***/ "../../../packages/curio.example-ui@1/sources/columnFilterBehavior.tsx"
/*!*****************************************************************************!*\
  !*** ../../../packages/curio.example-ui@1/sources/columnFilterBehavior.tsx ***!
  \*****************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   useColumnFilterBehavior: () => (/* binding */ useColumnFilterBehavior)
/* harmony export */ });
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! react */ "react");
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(react__WEBPACK_IMPORTED_MODULE_0__);
var _curio;
function _regenerator() { /*! regenerator-runtime -- Copyright (c) 2014-present, Facebook, Inc. -- license (MIT): https://github.com/babel/babel/blob/main/packages/babel-helpers/LICENSE */ var e, t, r = "function" == typeof Symbol ? Symbol : {}, n = r.iterator || "@@iterator", o = r.toStringTag || "@@toStringTag"; function i(r, n, o, i) { var c = n && n.prototype instanceof Generator ? n : Generator, u = Object.create(c.prototype); return _regeneratorDefine2(u, "_invoke", function (r, n, o) { var i, c, u, f = 0, p = o || [], y = !1, G = { p: 0, n: 0, v: e, a: d, f: d.bind(e, 4), d: function d(t, r) { return i = t, c = 0, u = e, G.n = r, a; } }; function d(r, n) { for (c = r, u = n, t = 0; !y && f && !o && t < p.length; t++) { var o, i = p[t], d = G.p, l = i[2]; r > 3 ? (o = l === n) && (u = i[(c = i[4]) ? 5 : (c = 3, 3)], i[4] = i[5] = e) : i[0] <= d && ((o = r < 2 && d < i[1]) ? (c = 0, G.v = n, G.n = i[1]) : d < l && (o = r < 3 || i[0] > n || n > l) && (i[4] = r, i[5] = n, G.n = l, c = 0)); } if (o || r > 1) return a; throw y = !0, n; } return function (o, p, l) { if (f > 1) throw TypeError("Generator is already running"); for (y && 1 === p && d(p, l), c = p, u = l; (t = c < 2 ? e : u) || !y;) { i || (c ? c < 3 ? (c > 1 && (G.n = -1), d(c, u)) : G.n = u : G.v = u); try { if (f = 2, i) { if (c || (o = "next"), t = i[o]) { if (!(t = t.call(i, u))) throw TypeError("iterator result is not an object"); if (!t.done) return t; u = t.value, c < 2 && (c = 0); } else 1 === c && (t = i["return"]) && t.call(i), c < 2 && (u = TypeError("The iterator does not provide a '" + o + "' method"), c = 1); i = e; } else if ((t = (y = G.n < 0) ? u : r.call(n, G)) !== a) break; } catch (t) { i = e, c = 1, u = t; } finally { f = 1; } } return { value: t, done: y }; }; }(r, o, i), !0), u; } var a = {}; function Generator() {} function GeneratorFunction() {} function GeneratorFunctionPrototype() {} t = Object.getPrototypeOf; var c = [][n] ? t(t([][n]())) : (_regeneratorDefine2(t = {}, n, function () { return this; }), t), u = GeneratorFunctionPrototype.prototype = Generator.prototype = Object.create(c); function f(e) { return Object.setPrototypeOf ? Object.setPrototypeOf(e, GeneratorFunctionPrototype) : (e.__proto__ = GeneratorFunctionPrototype, _regeneratorDefine2(e, o, "GeneratorFunction")), e.prototype = Object.create(u), e; } return GeneratorFunction.prototype = GeneratorFunctionPrototype, _regeneratorDefine2(u, "constructor", GeneratorFunctionPrototype), _regeneratorDefine2(GeneratorFunctionPrototype, "constructor", GeneratorFunction), GeneratorFunction.displayName = "GeneratorFunction", _regeneratorDefine2(GeneratorFunctionPrototype, o, "GeneratorFunction"), _regeneratorDefine2(u), _regeneratorDefine2(u, o, "Generator"), _regeneratorDefine2(u, n, function () { return this; }), _regeneratorDefine2(u, "toString", function () { return "[object Generator]"; }), (_regenerator = function _regenerator() { return { w: i, m: f }; })(); }
function _regeneratorDefine2(e, r, n, t) { var i = Object.defineProperty; try { i({}, "", {}); } catch (e) { i = 0; } _regeneratorDefine2 = function _regeneratorDefine(e, r, n, t) { function o(r, n) { _regeneratorDefine2(e, r, function (e) { return this._invoke(r, n, e); }); } r ? i ? i(e, r, { value: n, enumerable: !t, configurable: !t, writable: !t }) : e[r] = n : (o("next", 0), o("throw", 1), o("return", 2)); }, _regeneratorDefine2(e, r, n, t); }
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: !0, configurable: !0, writable: !0 }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == _typeof(i) ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != _typeof(t) || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r || "default"); if ("object" != _typeof(i)) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
function _createForOfIteratorHelper(r, e) { var t = "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (!t) { if (Array.isArray(r) || (t = _unsupportedIterableToArray(r)) || e && r && "number" == typeof r.length) { t && (r = t); var _n = 0, F = function F() {}; return { s: F, n: function n() { return _n >= r.length ? { done: !0 } : { done: !1, value: r[_n++] }; }, e: function e(r) { throw r; }, f: F }; } throw new TypeError("Invalid attempt to iterate non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); } var o, a = !0, u = !1; return { s: function s() { t = t.call(r); }, n: function n() { var r = t.next(); return a = r.done, r; }, e: function e(r) { u = !0, o = r; }, f: function f() { try { a || null == t["return"] || t["return"](); } finally { if (u) throw o; } } }; }
function _slicedToArray(r, e) { return _arrayWithHoles(r) || _iterableToArrayLimit(r, e) || _unsupportedIterableToArray(r, e) || _nonIterableRest(); }
function _nonIterableRest() { throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
function _iterableToArrayLimit(r, l) { var t = null == r ? null : "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (null != t) { var e, n, i, u, a = [], f = !0, o = !1; try { if (i = (t = t.call(r)).next, 0 === l) { if (Object(t) !== t) return; f = !1; } else for (; !(f = (e = i.call(t)).done) && (a.push(e.value), a.length !== l); f = !0); } catch (r) { o = !0, n = r; } finally { try { if (!f && null != t["return"] && (u = t["return"](), Object(u) !== u)) return; } finally { if (o) throw n; } } return a; } }
function _arrayWithHoles(r) { if (Array.isArray(r)) return r; }
function asyncGeneratorStep(n, t, e, r, o, a, c) { try { var i = n[a](c), u = i.value; } catch (n) { return void e(n); } i.done ? t(u) : Promise.resolve(u).then(r, o); }
function _asyncToGenerator(n) { return function () { var t = this, e = arguments; return new Promise(function (r, o) { var a = n.apply(t, e); function _next(n) { asyncGeneratorStep(a, r, o, _next, _throw, "next", n); } function _throw(n) { asyncGeneratorStep(a, r, o, _next, _throw, "throw", n); } _next(void 0); }); }; }
function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }

/**
 * Column Filter — a worked example of a node with its own React interface.
 *
 * This is the reference custom-UI node: small enough to read in one sitting,
 * with no API keys, no Python dependencies, and no backend endpoint of its
 * own. Fork it (or copy it into a package of your own) as the starting point
 * for a node that needs real controls rather than a code editor.
 *
 * What it demonstrates, in the order you meet each problem:
 *
 *   1. A behavior hook is a React custom hook. It receives the node's runtime
 *      `data` plus the shared `nodeState`, and returns only the parts of the
 *      node it wants to override — here `contentComponent`, the JSX rendered
 *      in the node body.
 *   2. Reading upstream data (`resolveInput` below). This is the part that
 *      surprises everyone: `data.input` is usually a *reference* to a sandbox
 *      artifact, not the data itself.
 *   3. Local UI state that does not touch the dataflow until the user asks
 *      for it (`useState` for the column / operator / threshold).
 *   4. Pushing a result downstream (`data.outputCallback`) and reporting
 *      success or failure through `nodeState.setOutput`.
 *
 * See docs/AUTHORING-NODES.md for the surrounding workflow (scaffold, build,
 * install, reload).
 */

/*
 * Read the host's backend URL at runtime.
 *
 * Do NOT use `process.env.BACKEND_URL` in a package bundle: webpack would
 * inline whatever URL your machine had at build time, and the bundle would
 * then point at your laptop for everyone who installs it. Curio's main bundle
 * publishes the live value on `window.curio.backendUrl` for exactly this.
 */
var BACKEND_URL = typeof window !== 'undefined' && ((_curio = window.curio) === null || _curio === void 0 ? void 0 : _curio.backendUrl) || '';

/** The session token lives in a cookie; the artifact endpoint requires it. */
function sessionToken() {
  if (typeof document === 'undefined') return '';
  var hit = document.cookie.match(/(?:^|;\s*)session_token=([^;]*)/);
  return hit ? decodeURIComponent(hit[1]) : '';
}

// Payload shapes Curio recognises directly. Anything else is a generic
// envelope wrapped around one of these, so peel until we reach a known type.
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
 *                                              which is what every Python or
 *                                              JS node produces -> fetch it
 *   { data: {...},    dataType: 'dataframe' }  an inline payload, which is what
 *                                              another custom-UI node produces
 *                                              -> use it as-is
 *
 * A node that only handles the second shape appears to work when wired to
 * another custom-UI node and then silently does nothing behind a Data Loading
 * node. Handle both.
 */
function resolveInput(_x) {
  return _resolveInput.apply(this, arguments);
}
/*
 * A `dataframe` payload is column-oriented. Two encodings of that reach this
 * node, and both must work:
 *
 *   array   { "population": [2746, 8804],        "name": ["Chicago", ...] }
 *   row map { "population": { "0": 2746, ... },  "name": { "0": "Chicago" } }
 *
 * The array form is what Curio actually produces: the sandbox serialises with
 * `to_dict(orient='list')` (sandbox/util/parsers.py). This node used to require
 * the row-map form and *explicitly reject* arrays, so `asFrame` returned null
 * for every real Curio DataFrame, `setFrame(null)` ran, and the node rendered
 * "Connect a DataFrame upstream and run that node." with nothing thrown and
 * nothing to debug (#194). The row-map form is kept because `to_dict()` with no
 * orient produces it, and hand-written specs use it.
 */
function _resolveInput() {
  _resolveInput = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee(input) {
    var _input$path;
    var ref, token, res, _t;
    return _regenerator().w(function (_context) {
      while (1) switch (_context.n) {
        case 0:
          if (!(input == null || input === '')) {
            _context.n = 1;
            break;
          }
          return _context.a(2, null);
        case 1:
          ref = typeof input === 'string' ? input : (_input$path = input.path) !== null && _input$path !== void 0 ? _input$path : input.dataset;
          if (!(typeof ref === 'string' && ref.trim())) {
            _context.n = 5;
            break;
          }
          token = sessionToken();
          _context.n = 2;
          return fetch("".concat(BACKEND_URL, "/get?fileName=").concat(encodeURIComponent(ref.trim())), {
            headers: token ? {
              Authorization: "Bearer ".concat(token)
            } : {}
          });
        case 2:
          res = _context.v;
          if (res.ok) {
            _context.n = 3;
            break;
          }
          throw new Error("Could not read upstream data (HTTP ".concat(res.status, ")"));
        case 3:
          _t = unwrap;
          _context.n = 4;
          return res.json();
        case 4:
          return _context.a(2, _t(_context.v));
        case 5:
          return _context.a(2, unwrap(input));
      }
    }, _callee);
  }));
  return _resolveInput.apply(this, arguments);
}
function asFrame(payload) {
  var frame = (payload === null || payload === void 0 ? void 0 : payload.dataType) === 'dataframe' ? payload.data : payload;
  // `Array.isArray` on the FRAME itself still rejects: a row-oriented list of
  // records is a different shape and is genuinely unsupported here.
  if (!frame || _typeof(frame) !== 'object' || Array.isArray(frame)) return null;
  var columns = Object.keys(frame);
  if (columns.length === 0) return null;
  // Each column may be an array or a row map; both are objects.
  var looksRight = columns.every(function (c) {
    return frame[c] && _typeof(frame[c]) === 'object';
  });
  return looksRight ? frame : null;
}

/** One cell, whichever encoding the column uses.
 *
 * Mirrors `utils/tabularPreview.ts`, which has always handled both. */
function cell(column, key) {
  return Array.isArray(column) ? column[Number(key)] : column[key];
}
function rowKeys(frame) {
  var first = Object.keys(frame)[0];
  if (!first) return [];
  var column = frame[first];
  // An array's row keys are its indices, as strings, so everything downstream
  // keeps working with string keys regardless of encoding.
  return Array.isArray(column) ? column.map(function (_, i) {
    return String(i);
  }) : Object.keys(column);
}

/** Columns whose values are numbers — the only ones worth thresholding. */
function numericColumns(frame) {
  return Object.keys(frame).filter(function (column) {
    var values = Object.values(frame[column]);
    var seen = values.filter(function (v) {
      return v != null;
    });
    return seen.length > 0 && seen.every(function (v) {
      return typeof v === 'number';
    });
  });
}
var COMPARE = {
  '>': function _(v, t) {
    return v > t;
  },
  '>=': function _(v, t) {
    return v >= t;
  },
  '<': function _(v, t) {
    return v < t;
  },
  '<=': function _(v, t) {
    return v <= t;
  }
};
var S = {
  root: {
    padding: '12px 14px',
    fontFamily: '"Roboto","Helvetica","Arial",sans-serif',
    fontSize: 13,
    color: '#333',
    display: 'flex',
    flexDirection: 'column',
    gap: 10
  },
  title: {
    fontSize: 14,
    fontWeight: 600,
    color: '#1a1a2e'
  },
  hint: {
    color: '#888',
    fontSize: 12,
    lineHeight: 1.4
  },
  error: {
    color: '#c0392b',
    fontSize: 12,
    lineHeight: 1.4
  },
  field: {
    display: 'flex',
    flexDirection: 'column',
    gap: 3
  },
  fieldLabel: {
    fontSize: 10,
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    color: '#94a3b8'
  },
  control: {
    padding: '5px 7px',
    border: '1px solid #cbd5e1',
    borderRadius: 6,
    fontSize: 12,
    background: '#fff'
  },
  row: {
    display: 'flex',
    gap: 8
  },
  summary: {
    background: '#f8fafc',
    border: '1px solid #e2e8f0',
    borderRadius: 8,
    padding: '8px 10px',
    fontSize: 12,
    color: '#475569'
  },
  button: {
    padding: '8px 12px',
    border: '1px solid #bbf7d0',
    borderRadius: 8,
    background: '#f0fdf4',
    color: '#166534',
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer'
  },
  buttonDisabled: {
    padding: '8px 12px',
    border: '1px solid #e5e7eb',
    borderRadius: 8,
    background: '#f3f4f6',
    color: '#9ca3af',
    fontSize: 12,
    fontWeight: 600,
    cursor: 'not-allowed'
  }
};
var useColumnFilterBehavior = function useColumnFilterBehavior(data, nodeState) {
  var _useState = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState2 = _slicedToArray(_useState, 2),
    frame = _useState2[0],
    setFrame = _useState2[1];
  var _useState3 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState4 = _slicedToArray(_useState3, 2),
    error = _useState4[0],
    setError = _useState4[1];
  var _useState5 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(''),
    _useState6 = _slicedToArray(_useState5, 2),
    column = _useState6[0],
    setColumn = _useState6[1];
  var _useState7 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)('>'),
    _useState8 = _slicedToArray(_useState7, 2),
    operator = _useState8[0],
    setOperator = _useState8[1];
  var _useState9 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)('0'),
    _useState0 = _slicedToArray(_useState9, 2),
    threshold = _useState0[0],
    setThreshold = _useState0[1];

  // Re-resolve whenever upstream produces something new. The `cancelled` flag
  // is the standard guard against a slow fetch resolving after the node has
  // moved on to a newer input.
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    var cancelled = false;
    setError(null);
    resolveInput(data.input).then(function (resolved) {
      if (cancelled) return;
      var next = asFrame(resolved);
      setFrame(next);
      if (next) {
        var _numeric = numericColumns(next);
        setColumn(function (prev) {
          var _numeric$;
          return prev && _numeric.includes(prev) ? prev : (_numeric$ = _numeric[0]) !== null && _numeric$ !== void 0 ? _numeric$ : '';
        });
      }
    })["catch"](function (e) {
      if (!cancelled) setError(e.message || String(e));
    });
    return function () {
      cancelled = true;
    };
  }, [data.input]);
  var numeric = (0,react__WEBPACK_IMPORTED_MODULE_0__.useMemo)(function () {
    return frame ? numericColumns(frame) : [];
  }, [frame]);

  // Which rows pass the current filter. Recomputed as the user types, but
  // nothing leaves the node until they press the button.
  var matching = (0,react__WEBPACK_IMPORTED_MODULE_0__.useMemo)(function () {
    if (!frame || !column) return null;
    var limit = Number(threshold);
    if (!Number.isFinite(limit)) return null;
    var compare = COMPARE[operator];
    return rowKeys(frame).filter(function (key) {
      var value = cell(frame[column], key);
      return typeof value === 'number' && compare(value, limit);
    });
  }, [frame, column, operator, threshold]);
  var totalRows = frame ? rowKeys(frame).length : 0;
  var emit = (0,react__WEBPACK_IMPORTED_MODULE_0__.useCallback)(function () {
    if (!frame || !matching) return;
    try {
      // Rebuild the column-oriented frame with only the matching row keys, so
      // downstream nodes receive the same shape they would from pandas.
      var filtered = {};
      var _loop = function _loop() {
        var name = _Object$keys[_i];
        var source = frame[name];
        // Preserve the input's encoding, so the downstream payload stays
        // byte-compatible with what `parseOutput` produced upstream.
        if (Array.isArray(source)) {
          filtered[name] = matching.map(function (key) {
            return cell(source, key);
          });
        } else {
          var kept = {};
          var _iterator = _createForOfIteratorHelper(matching),
            _step;
          try {
            for (_iterator.s(); !(_step = _iterator.n()).done;) {
              var key = _step.value;
              kept[key] = source[key];
            }
          } catch (err) {
            _iterator.e(err);
          } finally {
            _iterator.f();
          }
          filtered[name] = kept;
        }
      };
      for (var _i = 0, _Object$keys = Object.keys(frame); _i < _Object$keys.length; _i++) {
        _loop();
      }
      data.outputCallback(data.nodeId, {
        data: filtered,
        dataType: 'dataframe'
      });
      nodeState.setOutput({
        code: 'success',
        content: "".concat(matching.length, " of ").concat(totalRows, " rows sent downstream.")
      });
    } catch (e) {
      nodeState.setOutput({
        code: 'error',
        content: e.message || String(e)
      });
    }
  }, [frame, matching, totalRows, data, nodeState]);
  var body;
  if (error) {
    body = /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
      style: S.error
    }, error);
  } else if (!frame) {
    body = /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
      style: S.hint
    }, "Connect a DataFrame upstream and run that node. Any Data Loading or Data Transformation node works.");
  } else if (numeric.length === 0) {
    body = /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
      style: S.hint
    }, "This DataFrame has no numeric columns to filter on.");
  } else {
    body = /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement((react__WEBPACK_IMPORTED_MODULE_0___default().Fragment), null, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      style: S.field
    }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
      style: S.fieldLabel
    }, "Column"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("select", {
      style: S.control,
      value: column,
      onChange: function onChange(e) {
        return setColumn(e.target.value);
      }
    }, numeric.map(function (name) {
      return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("option", {
        key: name,
        value: name
      }, name);
    }))), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      style: S.row
    }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      style: _objectSpread(_objectSpread({}, S.field), {}, {
        flex: '0 0 84px'
      })
    }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
      style: S.fieldLabel
    }, "Keep"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("select", {
      style: S.control,
      value: operator,
      onChange: function onChange(e) {
        return setOperator(e.target.value);
      }
    }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("option", {
      value: ">"
    }, ">"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("option", {
      value: ">="
    }, "\u2265"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("option", {
      value: "<"
    }, "<"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("option", {
      value: "<="
    }, "\u2264"))), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      style: _objectSpread(_objectSpread({}, S.field), {}, {
        flex: 1
      })
    }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
      style: S.fieldLabel
    }, "Threshold"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("input", {
      style: S.control,
      type: "number",
      value: threshold,
      onChange: function onChange(e) {
        return setThreshold(e.target.value);
      }
    }))), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      style: S.summary
    }, matching == null ? 'Enter a number to filter on.' : "".concat(matching.length, " of ").concat(totalRows, " rows match.")), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
      type: "button",
      style: matching && matching.length > 0 ? S.button : S.buttonDisabled,
      disabled: !matching || matching.length === 0,
      onClick: emit
    }, "Send matching rows downstream"));
  }
  var contentComponent = /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.root,
    className: "nowheel"
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.title
  }, "Column Filter"), body);
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
/*!**************************************************************!*\
  !*** ../../../packages/curio.example-ui@1/sources/index.tsx ***!
  \**************************************************************/
__webpack_require__.r(__webpack_exports__);
/* harmony import */ var _columnFilterBehavior__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! ./columnFilterBehavior */ "../../../packages/curio.example-ui@1/sources/columnFilterBehavior.tsx");
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
 * shares Curio's own instances — two copies of React break every hook.
 */


function registerAll(curio) {
  curio.registerBehavior('column-filter', _columnFilterBehavior__WEBPACK_IMPORTED_MODULE_0__.useColumnFilterBehavior);
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