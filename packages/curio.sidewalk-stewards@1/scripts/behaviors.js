(function webpackUniversalModuleDefinition(root, factory) {
	if(typeof exports === 'object' && typeof module === 'object')
		module.exports = factory(require("react"));
	else if(typeof define === 'function' && define.amd)
		define(["react"], factory);
	else if(typeof exports === 'object')
		exports["curio_sidewalk-stewards_1"] = factory(require("react"));
	else
		root["curio_sidewalk-stewards_1"] = factory(root["React"]);
})(this, (__WEBPACK_EXTERNAL_MODULE_react__) => {
return /******/ (() => { // webpackBootstrap
/******/ 	"use strict";
/******/ 	var __webpack_modules__ = ({

/***/ "./node_modules/@fortawesome/free-solid-svg-icons/faCircleInfo.js"
/*!************************************************************************!*\
  !*** ./node_modules/@fortawesome/free-solid-svg-icons/faCircleInfo.js ***!
  \************************************************************************/
(__unused_webpack_module, exports) {


Object.defineProperty(exports, "__esModule", ({ value: true }));
var prefix = 'fas';
var iconName = 'circle-info';
var width = 512;
var height = 512;
var aliases = ["info-circle"];
var unicode = 'f05a';
var svgPathData = 'M256 512a256 256 0 1 0 0-512 256 256 0 1 0 0 512zM224 160a32 32 0 1 1 64 0 32 32 0 1 1 -64 0zm-8 64l48 0c13.3 0 24 10.7 24 24l0 88 8 0c13.3 0 24 10.7 24 24s-10.7 24-24 24l-80 0c-13.3 0-24-10.7-24-24s10.7-24 24-24l24 0 0-64-24 0c-13.3 0-24-10.7-24-24s10.7-24 24-24z';

exports.definition = {
  prefix: prefix,
  iconName: iconName,
  icon: [
    width,
    height,
    aliases,
    unicode,
    svgPathData
  ]};

exports.faCircleInfo = exports.definition;
exports.prefix = prefix;
exports.iconName = iconName;
exports.width = width;
exports.height = height;
exports.ligatures = aliases;
exports.unicode = unicode;
exports.svgPathData = svgPathData;
exports.aliases = aliases;

/***/ },

/***/ "./node_modules/@fortawesome/free-solid-svg-icons/faCopy.js"
/*!******************************************************************!*\
  !*** ./node_modules/@fortawesome/free-solid-svg-icons/faCopy.js ***!
  \******************************************************************/
(__unused_webpack_module, exports) {


Object.defineProperty(exports, "__esModule", ({ value: true }));
var prefix = 'fas';
var iconName = 'copy';
var width = 448;
var height = 512;
var aliases = [];
var unicode = 'f0c5';
var svgPathData = 'M192 0c-35.3 0-64 28.7-64 64l0 256c0 35.3 28.7 64 64 64l192 0c35.3 0 64-28.7 64-64l0-200.6c0-17.4-7.1-34.1-19.7-46.2L370.6 17.8C358.7 6.4 342.8 0 326.3 0L192 0zM64 128c-35.3 0-64 28.7-64 64L0 448c0 35.3 28.7 64 64 64l192 0c35.3 0 64-28.7 64-64l0-16-64 0 0 16-192 0 0-256 16 0 0-64-16 0z';

exports.definition = {
  prefix: prefix,
  iconName: iconName,
  icon: [
    width,
    height,
    aliases,
    unicode,
    svgPathData
  ]};

exports.faCopy = exports.definition;
exports.prefix = prefix;
exports.iconName = iconName;
exports.width = width;
exports.height = height;
exports.ligatures = aliases;
exports.unicode = unicode;
exports.svgPathData = svgPathData;
exports.aliases = aliases;

/***/ },

/***/ "./node_modules/@fortawesome/free-solid-svg-icons/faXmark.js"
/*!*******************************************************************!*\
  !*** ./node_modules/@fortawesome/free-solid-svg-icons/faXmark.js ***!
  \*******************************************************************/
(__unused_webpack_module, exports) {


Object.defineProperty(exports, "__esModule", ({ value: true }));
var prefix = 'fas';
var iconName = 'xmark';
var width = 384;
var height = 512;
var aliases = [128473,10005,10006,10060,215,"close","multiply","remove","times"];
var unicode = 'f00d';
var svgPathData = 'M55.1 73.4c-12.5-12.5-32.8-12.5-45.3 0s-12.5 32.8 0 45.3L147.2 256 9.9 393.4c-12.5 12.5-12.5 32.8 0 45.3s32.8 12.5 45.3 0L192.5 301.3 329.9 438.6c12.5 12.5 32.8 12.5 45.3 0s12.5-32.8 0-45.3L237.8 256 375.1 118.6c12.5-12.5 12.5-32.8 0-45.3s-32.8-12.5-45.3 0L192.5 210.7 55.1 73.4z';

exports.definition = {
  prefix: prefix,
  iconName: iconName,
  icon: [
    width,
    height,
    aliases,
    unicode,
    svgPathData
  ]};

exports.faXmark = exports.definition;
exports.prefix = prefix;
exports.iconName = iconName;
exports.width = width;
exports.height = height;
exports.ligatures = aliases;
exports.unicode = unicode;
exports.svgPathData = svgPathData;
exports.aliases = aliases;

/***/ },

/***/ "../../../packages/curio.sidewalk-stewards@1/sources/SidewalkTileEditor.tsx"
/*!**********************************************************************************!*\
  !*** ../../../packages/curio.sidewalk-stewards@1/sources/SidewalkTileEditor.tsx ***!
  \**********************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   DEFAULT_IMAGE_TEMPLATE: () => (/* binding */ DEFAULT_IMAGE_TEMPLATE),
/* harmony export */   DEFAULT_NETWORK_TEMPLATE: () => (/* binding */ DEFAULT_NETWORK_TEMPLATE),
/* harmony export */   SIDEWALK_EDIT_SCHEMA: () => (/* binding */ SIDEWALK_EDIT_SCHEMA),
/* harmony export */   SidewalkTileEditor: () => (/* binding */ SidewalkTileEditor),
/* harmony export */   clientToViewPoint: () => (/* binding */ clientToViewPoint),
/* harmony export */   parseSidewalkEditConfig: () => (/* binding */ parseSidewalkEditConfig),
/* harmony export */   shortestHeadingDelta: () => (/* binding */ shortestHeadingDelta),
/* harmony export */   viewToPoint: () => (/* binding */ viewToPoint)
/* harmony export */ });
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! react */ "react");
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(react__WEBPACK_IMPORTED_MODULE_0__);
/* harmony import */ var _fortawesome_free_solid_svg_icons_faCircleInfo__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! @fortawesome/free-solid-svg-icons/faCircleInfo */ "./node_modules/@fortawesome/free-solid-svg-icons/faCircleInfo.js");
/* harmony import */ var _fortawesome_free_solid_svg_icons_faCopy__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(/*! @fortawesome/free-solid-svg-icons/faCopy */ "./node_modules/@fortawesome/free-solid-svg-icons/faCopy.js");
/* harmony import */ var _fortawesome_free_solid_svg_icons_faXmark__WEBPACK_IMPORTED_MODULE_3__ = __webpack_require__(/*! @fortawesome/free-solid-svg-icons/faXmark */ "./node_modules/@fortawesome/free-solid-svg-icons/faXmark.js");
/* harmony import */ var _resourceResolver__WEBPACK_IMPORTED_MODULE_4__ = __webpack_require__(/*! ./resourceResolver */ "../../../packages/curio.sidewalk-stewards@1/sources/resourceResolver.ts");
/* harmony import */ var _selectedResources__WEBPACK_IMPORTED_MODULE_5__ = __webpack_require__(/*! ./selectedResources */ "../../../packages/curio.sidewalk-stewards@1/sources/selectedResources.ts");
/* harmony import */ var _sidewalkEditOperations__WEBPACK_IMPORTED_MODULE_6__ = __webpack_require__(/*! ./sidewalkEditOperations */ "../../../packages/curio.sidewalk-stewards@1/sources/sidewalkEditOperations.ts");
/* harmony import */ var _sidewalkTopology__WEBPACK_IMPORTED_MODULE_7__ = __webpack_require__(/*! ./sidewalkTopology */ "../../../packages/curio.sidewalk-stewards@1/sources/sidewalkTopology.ts");
/* harmony import */ var _networkEditContract__WEBPACK_IMPORTED_MODULE_8__ = __webpack_require__(/*! ./networkEditContract */ "../../../packages/curio.sidewalk-stewards@1/sources/networkEditContract.ts");
/* harmony import */ var _provenance__WEBPACK_IMPORTED_MODULE_9__ = __webpack_require__(/*! ./provenance */ "../../../packages/curio.sidewalk-stewards@1/sources/provenance.ts");
/* harmony import */ var _overviewData__WEBPACK_IMPORTED_MODULE_10__ = __webpack_require__(/*! ./overviewData */ "../../../packages/curio.sidewalk-stewards@1/sources/overviewData.ts");
/* harmony import */ var _streetViewContract__WEBPACK_IMPORTED_MODULE_11__ = __webpack_require__(/*! ./streetViewContract */ "../../../packages/curio.sidewalk-stewards@1/sources/streetViewContract.ts");
/* harmony import */ var _streetViewImages__WEBPACK_IMPORTED_MODULE_12__ = __webpack_require__(/*! ./streetViewImages */ "../../../packages/curio.sidewalk-stewards@1/sources/streetViewImages.ts");
/* harmony import */ var _cameraBoundary__WEBPACK_IMPORTED_MODULE_13__ = __webpack_require__(/*! ./cameraBoundary */ "../../../packages/curio.sidewalk-stewards@1/sources/cameraBoundary.ts");
/* harmony import */ var _tileNeighbors__WEBPACK_IMPORTED_MODULE_14__ = __webpack_require__(/*! ./tileNeighbors */ "../../../packages/curio.sidewalk-stewards@1/sources/tileNeighbors.ts");
/* harmony import */ var _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__ = __webpack_require__(/*! ./sidewalkNodeStyles */ "../../../packages/curio.sidewalk-stewards@1/sources/sidewalkNodeStyles.ts");
/* harmony import */ var _curio_streetvision_1_sources_nodeUiStyles__WEBPACK_IMPORTED_MODULE_16__ = __webpack_require__(/*! ../../curio.streetvision@1/sources/nodeUiStyles */ "../../../packages/curio.streetvision@1/sources/nodeUiStyles.ts");
/* harmony import */ var _curio_streetvision_1_sources_panoramaContract__WEBPACK_IMPORTED_MODULE_17__ = __webpack_require__(/*! ../../curio.streetvision@1/sources/panoramaContract */ "../../../packages/curio.streetvision@1/sources/panoramaContract.ts");
function _createForOfIteratorHelper(r, e) { var t = "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (!t) { if (Array.isArray(r) || (t = _unsupportedIterableToArray(r)) || e && r && "number" == typeof r.length) { t && (r = t); var _n = 0, F = function F() {}; return { s: F, n: function n() { return _n >= r.length ? { done: !0 } : { done: !1, value: r[_n++] }; }, e: function e(r) { throw r; }, f: F }; } throw new TypeError("Invalid attempt to iterate non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); } var o, a = !0, u = !1; return { s: function s() { t = t.call(r); }, n: function n() { var r = t.next(); return a = r.done, r; }, e: function e(r) { u = !0, o = r; }, f: function f() { try { a || null == t["return"] || t["return"](); } finally { if (u) throw o; } } }; }
function _toConsumableArray(r) { return _arrayWithoutHoles(r) || _iterableToArray(r) || _unsupportedIterableToArray(r) || _nonIterableSpread(); }
function _nonIterableSpread() { throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _iterableToArray(r) { if ("undefined" != typeof Symbol && null != r[Symbol.iterator] || null != r["@@iterator"]) return Array.from(r); }
function _arrayWithoutHoles(r) { if (Array.isArray(r)) return _arrayLikeToArray(r); }
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
function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: !0, configurable: !0, writable: !0 }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == _typeof(i) ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != _typeof(t) || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r || "default"); if ("object" != _typeof(i)) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }


















function panoramaRequestForInspection(inspection, reuseCurrent) {
  return _objectSpread({
    schema: _curio_streetvision_1_sources_panoramaContract__WEBPACK_IMPORTED_MODULE_17__.PANORAMA_REQUEST_SCHEMA,
    requestId: "".concat(inspection.editorId, ":").concat(inspection.selectionEpoch, ":").concat(inspection.selectionRevision, ":").concat(inspection.requestRevision),
    revision: inspection.requestRevision,
    location: inspection.location,
    crs: 'EPSG:4326'
  }, reuseCurrent ? {
    reuseCurrent: reuseCurrent
  } : {});
}

/** Match Stewards' shortest rotation across north (for example 350° → 10°). */
function shortestHeadingDelta(from, to) {
  return ((to - from) % 360 + 540) % 360 - 180;
}
var SIDEWALK_EDIT_SCHEMA = 'curio.sidewalk-tile-edit/v1';
// Resources must come from Prepare, explicit templates, or selected feature properties.
var DEFAULT_IMAGE_TEMPLATE = '';
var DEFAULT_NETWORK_TEMPLATE = '';
/** Use the same Font Awesome icon definitions as Curio's Details and Copy buttons. */
function CurioUtilityIcon(_ref) {
  var name = _ref.name;
  var icon = name === 'circle-info' ? _fortawesome_free_solid_svg_icons_faCircleInfo__WEBPACK_IMPORTED_MODULE_1__.faCircleInfo : name === 'copy' ? _fortawesome_free_solid_svg_icons_faCopy__WEBPACK_IMPORTED_MODULE_2__.faCopy : _fortawesome_free_solid_svg_icons_faXmark__WEBPACK_IMPORTED_MODULE_3__.faXmark;
  var paths = icon.icon[4];
  return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("svg", {
    "aria-hidden": "true",
    "data-icon": icon.iconName,
    viewBox: "0 0 ".concat(icon.icon[0], " ").concat(icon.icon[1]),
    width: "1em",
    height: "1em",
    fill: "currentColor"
  }, Array.isArray(paths) ? paths.map(function (path, index) {
    return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("path", {
      key: index,
      d: path
    });
  }) : /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("path", {
    d: paths
  }));
}

/** One centered chevron geometry for every direction, independent of font metrics. */
function TileNavigationChevron(_ref2) {
  var direction = _ref2.direction;
  var rotation = {
    north: '180deg',
    south: '0deg',
    east: '-90deg',
    west: '90deg'
  }[direction];
  return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("svg", {
    "aria-hidden": "true",
    "data-tile-chevron": direction,
    viewBox: "0 0 24 24",
    width: "20",
    height: "20",
    fill: "none",
    style: {
      display: 'block',
      transform: "rotate(".concat(rotation, ")")
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("path", {
    d: "M6 9l6 6 6-6",
    stroke: "currentColor",
    strokeWidth: "2.5",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }));
}
function EditToolIcon(_ref3) {
  var name = _ref3.name;
  var common = {
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round',
    strokeLinejoin: 'round'
  };
  if (name === 'draw') return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("svg", _extends({
    "aria-hidden": "true",
    viewBox: "0 0 24 24",
    width: "24",
    height: "24"
  }, common), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("path", {
    d: "M4 19 12 12 20 4"
  }), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("circle", {
    cx: "4",
    cy: "19",
    r: "2",
    fill: "currentColor"
  }), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("circle", {
    cx: "12",
    cy: "12",
    r: "2",
    fill: "currentColor"
  }), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("circle", {
    cx: "20",
    cy: "4",
    r: "2",
    fill: "currentColor"
  }));
  if (name === 'move') return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("svg", _extends({
    "aria-hidden": "true",
    viewBox: "0 0 24 24",
    width: "24",
    height: "24"
  }, common), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("path", {
    d: "M12 2v20M2 12h20m-10-10-3 3m3-3 3 3m-3 17-3-3m3 3 3-3M2 12l3-3m-3 3 3 3m17-3-3-3m3 3-3 3"
  }));
  if (name === 'delete') return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("svg", _extends({
    "aria-hidden": "true",
    viewBox: "0 0 24 24",
    width: "24",
    height: "24"
  }, common), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("path", {
    d: "M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7m4 4v5m4-5v5"
  }));
  if (name === 'inspect') return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("svg", _extends({
    "aria-hidden": "true",
    viewBox: "0 0 24 24",
    width: "24",
    height: "24"
  }, common), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("circle", {
    cx: "12",
    cy: "12",
    r: "7"
  }), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("circle", {
    cx: "12",
    cy: "12",
    r: "2",
    fill: "currentColor"
  }), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("path", {
    d: "M12 2v3m0 14v3M2 12h3m14 0h3"
  }));
  if (name === 'undo') return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("svg", _extends({
    "aria-hidden": "true",
    viewBox: "0 0 24 24",
    width: "24",
    height: "24"
  }, common), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("path", {
    d: "m9 7-5 5 5 5M4 12h9a6 6 0 0 1 6 6"
  }));
  return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("svg", _extends({
    "aria-hidden": "true",
    viewBox: "0 0 24 24",
    width: "24",
    height: "24"
  }, common), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("path", {
    d: "m15 7 5 5-5 5m5-5h-9a6 6 0 0 0-6 6"
  }));
}
function parseSidewalkEditConfig(raw) {
  try {
    var value = typeof raw === 'string' ? JSON.parse(raw || '{}') : raw;
    if (value && _typeof(value) === 'object' && value.schema === SIDEWALK_EDIT_SCHEMA) {
      var _overview$datasetId, _overview$gridUrl, _overview$networkUrl, _overview$boundariesU, _activeSelection, _activeSelection2;
      return _objectSpread(_objectSpread(_objectSpread(_objectSpread({
        schema: SIDEWALK_EDIT_SCHEMA
      }, value.mode === 'input-overview' ? {
        mode: 'input-overview'
      } : {}), {}, {
        imageUrlTemplate: String(value.imageUrlTemplate || DEFAULT_IMAGE_TEMPLATE),
        networkUrlTemplate: String(value.networkUrlTemplate || DEFAULT_NETWORK_TEMPLATE)
      }, value.overview ? {
        overview: _objectSpread(_objectSpread({}, value.overview.sourceIdentity ? {
          sourceIdentity: String(value.overview.sourceIdentity)
        } : {}), {}, {
          datasetId: String((_overview$datasetId = value.overview.datasetId) !== null && _overview$datasetId !== void 0 ? _overview$datasetId : ''),
          gridUrl: String((_overview$gridUrl = value.overview.gridUrl) !== null && _overview$gridUrl !== void 0 ? _overview$gridUrl : ''),
          networkUrl: String((_overview$networkUrl = value.overview.networkUrl) !== null && _overview$networkUrl !== void 0 ? _overview$networkUrl : ''),
          boundariesUrl: String((_overview$boundariesU = value.overview.boundariesUrl) !== null && _overview$boundariesU !== void 0 ? _overview$boundariesU : '')
        })
      } : {}), (_activeSelection = value.activeSelection) !== null && _activeSelection !== void 0 && _activeSelection.tileId && (_activeSelection2 = value.activeSelection) !== null && _activeSelection2 !== void 0 && _activeSelection2.sourceFingerprint ? {
        activeSelection: {
          tileId: String(value.activeSelection.tileId),
          sourceFingerprint: String(value.activeSelection.sourceFingerprint)
        }
      } : {}), {}, {
        byTile: value.byTile && _typeof(value.byTile) === 'object' ? value.byTile : {}
      });
    }
  } catch (_unused) {/* an empty or old code buffer uses defaults */}
  return {
    schema: SIDEWALK_EDIT_SCHEMA,
    imageUrlTemplate: DEFAULT_IMAGE_TEMPLATE,
    networkUrlTemplate: DEFAULT_NETWORK_TEMPLATE,
    byTile: {}
  };
}
function unwrap(value) {
  if (!value || _typeof(value) !== 'object') return value;
  if (value.type === 'FeatureCollection') return value;
  if (value.dataType === 'geodataframe' || value.dataType === 'geojson') return unwrap(value.data);
  if (value.data && _typeof(value.data) === 'object') return unwrap(value.data);
  if (value.content && _typeof(value.content) === 'object') return unwrap(value.content);
  return value;
}
function resolveSelection(_x, _x2) {
  return _resolveSelection.apply(this, arguments);
}
function _resolveSelection() {
  _resolveSelection = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee2(value, signal) {
    var _raw, _raw2, _raw3;
    var raw, reference, result, _t4, _t5;
    return _regenerator().w(function (_context2) {
      while (1) switch (_context2.p = _context2.n) {
        case 0:
          raw = unwrap(value);
          if (!(typeof raw === 'string' && raw.trim())) {
            _context2.n = 4;
            break;
          }
          reference = raw.trim();
          _context2.p = 1;
          raw = unwrap(JSON.parse(reference));
          _context2.n = 4;
          break;
        case 2:
          _context2.p = 2;
          _t4 = _context2.v;
          _t5 = unwrap;
          _context2.n = 3;
          return (0,_resourceResolver__WEBPACK_IMPORTED_MODULE_4__.fetchData)(reference, signal);
        case 3:
          raw = _t5(_context2.v);
        case 4:
          if (!((_raw = raw) !== null && _raw !== void 0 && _raw.path && !raw.features)) {
            _context2.n = 6;
            break;
          }
          _context2.n = 5;
          return (0,_resourceResolver__WEBPACK_IMPORTED_MODULE_4__.fetchData)(raw.path, signal);
        case 5:
          result = _context2.v;
          raw = unwrap(result);
        case 6:
          if (!(((_raw2 = raw) === null || _raw2 === void 0 ? void 0 : _raw2.type) === 'Feature' && raw.geometry)) {
            _context2.n = 7;
            break;
          }
          return _context2.a(2, {
            type: 'FeatureCollection',
            features: [raw]
          });
        case 7:
          if (!(((_raw3 = raw) === null || _raw3 === void 0 ? void 0 : _raw3.type) === 'FeatureCollection' && Array.isArray(raw.features))) {
            _context2.n = 8;
            break;
          }
          return _context2.a(2, raw);
        case 8:
          return _context2.a(2, null);
      }
    }, _callee2, null, [[1, 2]]);
  }));
  return _resolveSelection.apply(this, arguments);
}
function fileUrl(path) {
  return (0,_resourceResolver__WEBPACK_IMPORTED_MODULE_4__.assetUrl)(path);
}
function loadNetwork(_x3, _x4) {
  return _loadNetwork.apply(this, arguments);
}
function _loadNetwork() {
  _loadNetwork = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee3(path, signal) {
    var response, raw, _t6;
    return _regenerator().w(function (_context3) {
      while (1) switch (_context3.n) {
        case 0:
          _context3.n = 1;
          return fetch(fileUrl(path), {
            signal: signal
          });
        case 1:
          response = _context3.v;
          if (response.ok) {
            _context3.n = 2;
            break;
          }
          throw new Error("Network data could not be loaded (".concat(response.status, ")."));
        case 2:
          _t6 = unwrap;
          _context3.n = 3;
          return response.json();
        case 3:
          raw = _t6(_context3.v);
          if (!((raw === null || raw === void 0 ? void 0 : raw.type) !== 'FeatureCollection' || !Array.isArray(raw.features))) {
            _context3.n = 4;
            break;
          }
          throw new Error('The network asset must be a GeoJSON FeatureCollection.');
        case 4:
          return _context3.a(2, raw);
      }
    }, _callee3);
  }));
  return _loadNetwork.apply(this, arguments);
}
var VIEW = 1000;
var OUTSIDE_CAMERA_TAG_WIDTH = 485;
var OUTSIDE_CAMERA_TAG_HEIGHT = 52;
// Marker dimensions are in the editor's 1000-unit image coordinate space.
// React Flow zoom scales the image and its markers together.
var STEWARDS_CAMERA_SIZE = 40;
var CAMERA_CUE_MARGIN = STEWARDS_CAMERA_SIZE / 2 + 6;
var NETWORK_NODE_RADIUS = 10;
var NETWORK_STROKE = '#f07800';
var NETWORK_STROKE_WIDTH = 3;
var coordinateKey = function coordinateKey(point) {
  return "".concat(Math.round(point[0] * 1e8) / 1e8, ",").concat(Math.round(point[1] * 1e8) / 1e8);
};
var emptyFC = {
  type: 'FeatureCollection',
  features: []
};
function pointToView(p, bounds) {
  var width = Math.max(bounds[2] - bounds[0], 1e-12);
  var height = Math.max(bounds[3] - bounds[1], 1e-12);
  return [(p[0] - bounds[0]) / width * VIEW, VIEW - (p[1] - bounds[1]) / height * VIEW];
}
function viewToPoint(x, y, bounds) {
  return [bounds[0] + x / VIEW * (bounds[2] - bounds[0]), bounds[3] - y / VIEW * (bounds[3] - bounds[1])];
}
/** The image and SVG occupy the same aspect-preserving canvas. */
function clientToViewPoint(rect, clientX, clientY) {
  if (rect.width <= 0 || rect.height <= 0) throw new Error('Editor image has no visible area.');
  return [(clientX - rect.left) / rect.width * VIEW, (clientY - rect.top) / rect.height * VIEW];
}
function linePath(feature, bounds) {
  var _feature$geometry;
  if (((_feature$geometry = feature.geometry) === null || _feature$geometry === void 0 ? void 0 : _feature$geometry.type) !== 'LineString') return '';
  return feature.geometry.coordinates.map(function (p, i) {
    var _pointToView = pointToView(p, bounds),
      _pointToView2 = _slicedToArray(_pointToView, 2),
      x = _pointToView2[0],
      y = _pointToView2[1];
    return "".concat(i ? 'L' : 'M').concat(x, ",").concat(y);
  }).join(' ');
}
function closestLineSegment(fc, p) {
  var best = null;
  fc.features.forEach(function (f, featureIndex) {
    var _f$geometry;
    if (((_f$geometry = f.geometry) === null || _f$geometry === void 0 ? void 0 : _f$geometry.type) !== 'LineString') return;
    for (var i = 1; i < f.geometry.coordinates.length; i += 1) {
      var a = f.geometry.coordinates[i - 1];
      var b = f.geometry.coordinates[i];
      var dx = b[0] - a[0];
      var dy = b[1] - a[1];
      var d2 = dx * dx + dy * dy || 1;
      var t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / d2));
      var distance = Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
      if (!best || distance < best.distance) best = {
        featureIndex: featureIndex,
        segmentIndex: i - 1,
        distance: distance,
        point: [a[0] + t * dx, a[1] + t * dy]
      };
    }
  });
  return best;
}
function SidewalkTileEditor(_ref4) {
  var _globalThis$crypto$ra, _globalThis$crypto, _globalThis$crypto$ra2, _config$overview, _selection$features, _ref5, _tileFeature$properti, _tileFeature$properti2, _tileFeature$properti3, _tileFeature$properti4, _config$overview2, _tileFeature$properti5, _currentActiveTile$cu2, _currentActiveTile$cu3, _currentActiveTile$cu4, _currentActiveTile$cu5;
  var nodeId = _ref4.nodeId,
    input = _ref4.input,
    originalNetwork = _ref4.originalNetwork,
    selectionIndex = _ref4.selectionIndex,
    _ref4$allowSingleTile = _ref4.allowSingleTile,
    allowSingleTile = _ref4$allowSingleTile === void 0 ? true : _ref4$allowSingleTile,
    selectionFeatureId = _ref4.selectionFeatureId,
    selectionFeature = _ref4.selectionFeature,
    sourceFingerprint = _ref4.sourceFingerprint,
    incomingInteractions = _ref4.incomingInteractions,
    config = _ref4.config,
    persist = _ref4.persist,
    emit = _ref4.emit,
    onCommitted = _ref4.onCommitted,
    interactionsCallback = _ref4.interactionsCallback,
    setStatus = _ref4.setStatus,
    neighborIndex = _ref4.neighborIndex,
    onNavigate = _ref4.onNavigate;
  var _useState = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState2 = _slicedToArray(_useState, 2),
    selection = _useState2[0],
    setSelection = _useState2[1];
  var _useState3 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(emptyFC),
    _useState4 = _slicedToArray(_useState3, 2),
    network = _useState4[0],
    setNetwork = _useState4[1];
  var _useState5 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(emptyFC),
    _useState6 = _slicedToArray(_useState5, 2),
    sourceNetwork = _useState6[0],
    setSourceNetwork = _useState6[1];
  var _useState7 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState8 = _slicedToArray(_useState7, 2),
    bounds = _useState8[0],
    setBounds = _useState8[1];
  var _useState9 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState0 = _slicedToArray(_useState9, 2),
    tileCrs = _useState0[0],
    setTileCrs = _useState0[1];
  var _useState1 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(''),
    _useState10 = _slicedToArray(_useState1, 2),
    imageUrl = _useState10[0],
    setImageUrl = _useState10[1];
  var _useState11 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(false),
    _useState12 = _slicedToArray(_useState11, 2),
    loading = _useState12[0],
    setLoading = _useState12[1];
  var _useState13 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(''),
    _useState14 = _slicedToArray(_useState13, 2),
    error = _useState14[0],
    setError = _useState14[1];
  var _useState15 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(false),
    _useState16 = _slicedToArray(_useState15, 2),
    imageReady = _useState16[0],
    setImageReady = _useState16[1];
  var _useState17 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(1),
    _useState18 = _slicedToArray(_useState17, 2),
    imageAspect = _useState18[0],
    setImageAspect = _useState18[1];
  var _useState19 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(0),
    _useState20 = _slicedToArray(_useState19, 2),
    imageGeneration = _useState20[0],
    setImageGeneration = _useState20[1];
  var imageSvg = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)(null);
  var _useState21 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(1),
    _useState22 = _slicedToArray(_useState21, 2),
    markerAspect = _useState22[0],
    setMarkerAspect = _useState22[1];
  var requestGeneration = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)(0);
  var selectionEpoch = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)("".concat(new Date().toISOString(), ":").concat((_globalThis$crypto$ra = (_globalThis$crypto = globalThis.crypto) === null || _globalThis$crypto === void 0 || (_globalThis$crypto$ra2 = _globalThis$crypto.randomUUID) === null || _globalThis$crypto$ra2 === void 0 ? void 0 : _globalThis$crypto$ra2.call(_globalThis$crypto)) !== null && _globalThis$crypto$ra !== void 0 ? _globalThis$crypto$ra : Math.random().toString(36).slice(2)));
  var selectionRevision = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)(0);
  var currentActiveTile = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)(null);
  var callbackRef = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)(interactionsCallback);
  callbackRef.current = interactionsCallback;
  var _useState23 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState24 = _slicedToArray(_useState23, 2),
    camera = _useState24[0],
    setCamera = _useState24[1];
  var _useState25 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState26 = _slicedToArray(_useState25, 2),
    displayHeading = _useState26[0],
    setDisplayHeading = _useState26[1];
  var accumulatedHeading = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)(null);
  var cameraRevisions = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)(new Map());
  var fingerprint = sourceFingerprint !== null && sourceFingerprint !== void 0 ? sourceFingerprint : (0,_streetViewContract__WEBPACK_IMPORTED_MODULE_11__.sourceFingerprint)((_config$overview = config.overview) === null || _config$overview === void 0 ? void 0 : _config$overview.sourceIdentity, config.imageUrlTemplate, config.networkUrlTemplate, input);
  var request = (0,react__WEBPACK_IMPORTED_MODULE_0__.useMemo)(function () {
    return {
      input: input,
      originalNetwork: originalNetwork,
      selectionIndex: selectionIndex,
      selectionFeatureId: selectionFeatureId,
      selectionFeature: selectionFeature,
      allowSingleTile: allowSingleTile,
      imageTemplate: config.imageUrlTemplate,
      networkTemplate: config.networkUrlTemplate
    };
  }, [input, originalNetwork, selectionIndex, selectionFeatureId, selectionFeature, allowSingleTile, config.imageUrlTemplate, config.networkUrlTemplate]);
  var _useState27 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState28 = _slicedToArray(_useState27, 2),
    loadedRequest = _useState28[0],
    setLoadedRequest = _useState28[1];
  var configRef = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)(config);
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    configRef.current = config;
  }, [config]);
  var persistConfig = function persistConfig(next) {
    var scoped = (0,_overviewData__WEBPACK_IMPORTED_MODULE_10__.scopeLegacyTiles)(next);
    configRef.current = scoped;
    persist(scoped);
  };
  var _useState29 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)('select'),
    _useState30 = _slicedToArray(_useState29, 2),
    mode = _useState30[0],
    setMode = _useState30[1];
  var _useState31 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(false),
    _useState32 = _slicedToArray(_useState31, 2),
    sourcesOpen = _useState32[0],
    setSourcesOpen = _useState32[1];
  var _useState33 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(false),
    _useState34 = _slicedToArray(_useState33, 2),
    warningsOpen = _useState34[0],
    setWarningsOpen = _useState34[1];
  var _useState35 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(''),
    _useState36 = _slicedToArray(_useState35, 2),
    copyStatus = _useState36[0],
    setCopyStatus = _useState36[1];
  var sourcesButton = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)(null);
  var sourcesPanel = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)(null);
  var suppressOutsideClick = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)(false);
  var _useState37 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState38 = _slicedToArray(_useState37, 2),
    navigationTarget = _useState38[0],
    setNavigationTarget = _useState38[1];
  var _useState39 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(''),
    _useState40 = _slicedToArray(_useState39, 2),
    movementNotice = _useState40[0],
    setMovementNotice = _useState40[1];
  var _useState41 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState42 = _slicedToArray(_useState41, 2),
    requestedPoint = _useState42[0],
    setRequestedPoint = _useState42[1];
  var _useState43 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState44 = _slicedToArray(_useState43, 2),
    inspectionStatus = _useState44[0],
    setInspectionStatus = _useState44[1];
  var inspectionRevision = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)(0);
  var currentInspection = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)(null);
  var pendingCameraAdoption = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)(null);
  var _useState45 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)([]),
    _useState46 = _slicedToArray(_useState45, 2),
    drawing = _useState46[0],
    setDrawing = _useState46[1];
  var drawingRef = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)([]);
  var pendingDraw = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)(null);
  var _useState47 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState48 = _slicedToArray(_useState47, 2),
    drawingCursor = _useState48[0],
    setDrawingCursor = _useState48[1];
  var _useState49 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState50 = _slicedToArray(_useState49, 2),
    marqueeStart = _useState50[0],
    setMarqueeStart = _useState50[1];
  var _useState51 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState52 = _slicedToArray(_useState51, 2),
    marqueeEnd = _useState52[0],
    setMarqueeEnd = _useState52[1];
  var _useState53 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState54 = _slicedToArray(_useState53, 2),
    selectedNode = _useState54[0],
    setSelectedNode = _useState54[1];
  var _useState55 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)([]),
    _useState56 = _slicedToArray(_useState55, 2),
    past = _useState56[0],
    setPast = _useState56[1];
  var _useState57 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)([]),
    _useState58 = _slicedToArray(_useState57, 2),
    future = _useState58[0],
    setFuture = _useState58[1];
  var _useState59 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)([]),
    _useState60 = _slicedToArray(_useState59, 2),
    futureOperations = _useState60[0],
    setFutureOperations = _useState60[1];
  var _useState61 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)([]),
    _useState62 = _slicedToArray(_useState61, 2),
    operations = _useState62[0],
    setOperations = _useState62[1];
  var _useState63 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState64 = _slicedToArray(_useState63, 2),
    drag = _useState64[0],
    setDrag = _useState64[1];
  var dragMoved = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)(false);
  drawingRef.current = drawing;
  var tileFeature = selection === null || selection === void 0 || (_selection$features = selection.features) === null || _selection$features === void 0 ? void 0 : _selection$features[0];
  var tileId = String((_ref5 = (_tileFeature$properti = tileFeature === null || tileFeature === void 0 || (_tileFeature$properti2 = tileFeature.properties) === null || _tileFeature$properti2 === void 0 ? void 0 : _tileFeature$properti2.tile_id) !== null && _tileFeature$properti !== void 0 ? _tileFeature$properti : tileFeature === null || tileFeature === void 0 || (_tileFeature$properti3 = tileFeature.properties) === null || _tileFeature$properti3 === void 0 ? void 0 : _tileFeature$properti3.tileId) !== null && _ref5 !== void 0 ? _ref5 : '');
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    return setWarningsOpen(false);
  }, [tileId]);
  var ready = !!tileId && loadedRequest === request && !loading && !error && imageReady;
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    if (navigationTarget && tileId === navigationTarget && (ready || error)) setNavigationTarget(null);
  }, [navigationTarget, tileId, ready, error]);
  var tileBounds = (0,_sidewalkEditOperations__WEBPACK_IMPORTED_MODULE_6__.featureBounds)(tileFeature);
  var viewBounds = bounds !== null && bounds !== void 0 ? bounds : tileBounds;
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    var svg = imageSvg.current;
    if (!svg) return;
    // The image overlay stretches its 1000-unit viewBox to the editor panel.
    // Correct marker shapes for that aspect ratio, without counter-scaling zoom.
    var measure = function measure() {
      var _svg$getBoundingClien = svg.getBoundingClientRect(),
        width = _svg$getBoundingClien.width,
        height = _svg$getBoundingClien.height;
      if (width > 0 && height > 0) {
        var aspect = width / height;
        setMarkerAspect(function (previous) {
          return Math.abs(previous - aspect) > 0.001 ? aspect : previous;
        });
      }
    };
    measure();
    var observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
    observer === null || observer === void 0 || observer.observe(svg);
    window.addEventListener('resize', measure);
    return function () {
      observer === null || observer === void 0 || observer.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, [ready, tileId]);
  var sendActiveTile = (0,react__WEBPACK_IMPORTED_MODULE_0__.useCallback)(function (feature, crs) {
    var _ref6, _feature$properties$t, _feature$properties, _feature$properties2, _callbackRef$current;
    var previousInspection = currentInspection.current;
    var id = feature ? String((_ref6 = (_feature$properties$t = (_feature$properties = feature.properties) === null || _feature$properties === void 0 ? void 0 : _feature$properties.tile_id) !== null && _feature$properties$t !== void 0 ? _feature$properties$t : (_feature$properties2 = feature.properties) === null || _feature$properties2 === void 0 ? void 0 : _feature$properties2.tileId) !== null && _ref6 !== void 0 ? _ref6 : '') : null;
    if (feature && !id) throw new Error('Selected tile has no tile ID.');
    var next = {
      schema: _streetViewContract__WEBPACK_IMPORTED_MODULE_11__.ACTIVE_TILE_SCHEMA,
      editorId: nodeId,
      sourceFingerprint: fingerprint,
      selectionEpoch: selectionEpoch.current,
      selectionRevision: ++selectionRevision.current,
      tileId: id,
      geometry: feature ? (0,_streetViewContract__WEBPACK_IMPORTED_MODULE_11__.tileGeometryWgs84)(feature, crs) : null,
      crs: 'EPSG:4326'
    };
    currentActiveTile.current = next;
    // A panorama continues to report its location while the editor switches tiles.
    // Keep that accepted camera context so every tile can show whether it contains it.
    // A new inspection supersedes this request; clearing the tile removes it.
    if (!id || (previousInspection === null || previousInspection === void 0 ? void 0 : previousInspection.sourceFingerprint) !== fingerprint) {
      currentInspection.current = null;
      setRequestedPoint(null);
      setInspectionStatus(null);
      cameraRevisions.current.clear();
      setCamera(null);
      accumulatedHeading.current = null;
      setDisplayHeading(null);
    }
    (_callbackRef$current = callbackRef.current) === null || _callbackRef$current === void 0 || _callbackRef$current.call(callbackRef, _objectSpread(_defineProperty({}, _streetViewContract__WEBPACK_IMPORTED_MODULE_11__.ACTIVE_TILE_CHANNEL, next), !id && previousInspection ? _defineProperty({}, _curio_streetvision_1_sources_panoramaContract__WEBPACK_IMPORTED_MODULE_17__.PANORAMA_CONTEXT_CHANNEL, {
      schema: _curio_streetvision_1_sources_panoramaContract__WEBPACK_IMPORTED_MODULE_17__.PANORAMA_CONTEXT_SCHEMA,
      requestId: panoramaRequestForInspection(previousInspection).requestId,
      revision: previousInspection.requestRevision,
      active: false
    }) : {}), nodeId);
    var adoption = pendingCameraAdoption.current;
    if (id && (adoption === null || adoption === void 0 ? void 0 : adoption.tileId) === id && adoption.camera.location) {
      var _callbackRef$current2;
      pendingCameraAdoption.current = null;
      var inspection = {
        schema: _streetViewContract__WEBPACK_IMPORTED_MODULE_11__.INSPECTION_REQUEST_SCHEMA,
        editorId: next.editorId,
        sourceFingerprint: next.sourceFingerprint,
        selectionEpoch: next.selectionEpoch,
        selectionRevision: next.selectionRevision,
        requestRevision: ++inspectionRevision.current,
        tileId: id,
        location: adoption.camera.location,
        crs: 'EPSG:4326'
      };
      currentInspection.current = inspection;
      setRequestedPoint(inspection.location);
      setInspectionStatus(null);
      (_callbackRef$current2 = callbackRef.current) === null || _callbackRef$current2 === void 0 || _callbackRef$current2.call(callbackRef, _defineProperty(_defineProperty(_defineProperty({}, _streetViewContract__WEBPACK_IMPORTED_MODULE_11__.ACTIVE_TILE_CHANNEL, next), _streetViewContract__WEBPACK_IMPORTED_MODULE_11__.INSPECTION_REQUEST_CHANNEL, inspection), _curio_streetvision_1_sources_panoramaContract__WEBPACK_IMPORTED_MODULE_17__.PANORAMA_REQUEST_CHANNEL, panoramaRequestForInspection(inspection, {
        viewerId: adoption.camera.viewerId,
        panoId: adoption.camera.imageId
      })), nodeId);
    }
  }, [nodeId, fingerprint]);
  var incomingRequest = (0,_streetViewContract__WEBPACK_IMPORTED_MODULE_11__.latestActiveTileRequest)(incomingInteractions);
  var lastRepliedRequest = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)('');
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    var _incomingRequest$view, _callbackRef$current4;
    if (!incomingRequest || !currentActiveTile.current) return;
    // A request may arrive while restoration has only published the empty
    // tile. Reply again when the restored active tile gets its own revision.
    var key = "".concat(incomingRequest.viewerId, ":").concat((_incomingRequest$view = incomingRequest.viewerEpoch) !== null && _incomingRequest$view !== void 0 ? _incomingRequest$view : '', ":").concat(incomingRequest.requestRevision, ":").concat(currentActiveTile.current.selectionRevision);
    if (lastRepliedRequest.current === key) return;
    lastRepliedRequest.current = key;
    (_callbackRef$current4 = callbackRef.current) === null || _callbackRef$current4 === void 0 || _callbackRef$current4.call(callbackRef, _objectSpread(_objectSpread(_defineProperty({}, _streetViewContract__WEBPACK_IMPORTED_MODULE_11__.ACTIVE_TILE_CHANNEL, currentActiveTile.current), currentInspection.current ? _defineProperty({}, _streetViewContract__WEBPACK_IMPORTED_MODULE_11__.INSPECTION_REQUEST_CHANNEL, currentInspection.current) : {}), currentInspection.current ? _defineProperty({}, _curio_streetvision_1_sources_panoramaContract__WEBPACK_IMPORTED_MODULE_17__.PANORAMA_REQUEST_CHANNEL, panoramaRequestForInspection(currentInspection.current)) : {}), nodeId);
  }, [incomingRequest, nodeId, tileId]);
  var incomingCamera = (0,_streetViewContract__WEBPACK_IMPORTED_MODULE_11__.latestCameraContext)(incomingInteractions);
  var incomingPanoramaCamera = (0,_curio_streetvision_1_sources_panoramaContract__WEBPACK_IMPORTED_MODULE_17__.latestPanoramaCamera)(incomingInteractions);
  var incomingPanoramaStatus = (0,_curio_streetvision_1_sources_panoramaContract__WEBPACK_IMPORTED_MODULE_17__.latestPanoramaStatus)(incomingInteractions);
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    var inspection = currentInspection.current;
    if (!inspection || !incomingPanoramaStatus || incomingPanoramaStatus.requestId !== panoramaRequestForInspection(inspection).requestId || incomingPanoramaStatus.revision !== inspection.requestRevision) return;
    setInspectionStatus(function (previous) {
      return (previous === null || previous === void 0 ? void 0 : previous.requestId) === incomingPanoramaStatus.requestId && previous.revision === incomingPanoramaStatus.revision && previous.viewerId === incomingPanoramaStatus.viewerId && previous.state === incomingPanoramaStatus.state && previous.message === incomingPanoramaStatus.message ? previous : incomingPanoramaStatus;
    });
  }, [incomingPanoramaStatus]);
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    var pending = pendingCameraAdoption.current;
    if (!pending || !incomingPanoramaCamera || incomingPanoramaCamera.requestId !== pending.requestId || incomingPanoramaCamera.revision !== pending.revision || incomingPanoramaCamera.viewerId !== pending.camera.viewerId || incomingPanoramaCamera.cameraRevision <= pending.cameraRevision) return;
    // Native movement may continue while the destination image/network loads.
    // Follow that same viewer, but never silently change the chosen destination.
    pending.cameraRevision = incomingPanoramaCamera.cameraRevision;
    pending.camera = _objectSpread(_objectSpread({}, pending.camera), {}, {
      imageId: incomingPanoramaCamera.panoId,
      location: incomingPanoramaCamera.actualLocation,
      headingDegrees: incomingPanoramaCamera.headingDegrees
    });
  }, [incomingPanoramaCamera]);
  var acceptCamera = function acceptCamera(next) {
    if ((next === null || next === void 0 ? void 0 : next.headingDegrees) != null && next.headingMeaning) {
      var heading = (next.headingDegrees % 360 + 360) % 360;
      var previous = accumulatedHeading.current;
      var continuous = previous === null ? heading : previous + shortestHeadingDelta(previous, heading);
      accumulatedHeading.current = continuous;
      setDisplayHeading(continuous);
    } else {
      accumulatedHeading.current = null;
      setDisplayHeading(null);
    }
    setCamera(next);
  };
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    var _currentInspection$cu, _currentInspection$cu2, _incomingCamera$reque, _cameraRevisions$curr;
    if (!incomingCamera || !currentActiveTile.current || !(0,_streetViewContract__WEBPACK_IMPORTED_MODULE_11__.cameraMatchesTile)(incomingCamera, currentActiveTile.current)) return;
    var expectedRequest = (_currentInspection$cu = (_currentInspection$cu2 = currentInspection.current) === null || _currentInspection$cu2 === void 0 ? void 0 : _currentInspection$cu2.requestRevision) !== null && _currentInspection$cu !== void 0 ? _currentInspection$cu : null;
    if (((_incomingCamera$reque = incomingCamera.requestRevision) !== null && _incomingCamera$reque !== void 0 ? _incomingCamera$reque : null) !== expectedRequest) return;
    var previous = (_cameraRevisions$curr = cameraRevisions.current.get(incomingCamera.viewerId)) !== null && _cameraRevisions$curr !== void 0 ? _cameraRevisions$curr : -1;
    if (incomingCamera.displayRevision < previous) return;
    cameraRevisions.current.set(incomingCamera.viewerId, incomingCamera.displayRevision);
    acceptCamera(incomingCamera.location ? incomingCamera : null);
  }, [incomingCamera]);
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    var _cameraRevisions$curr2;
    var inspection = currentInspection.current;
    var active = currentActiveTile.current;
    if (!incomingPanoramaCamera || !inspection || !(active !== null && active !== void 0 && active.tileId) || incomingPanoramaCamera.requestId !== panoramaRequestForInspection(inspection).requestId || incomingPanoramaCamera.revision !== inspection.requestRevision) return;
    var previous = (_cameraRevisions$curr2 = cameraRevisions.current.get(incomingPanoramaCamera.viewerId)) !== null && _cameraRevisions$curr2 !== void 0 ? _cameraRevisions$curr2 : -1;
    if (incomingPanoramaCamera.cameraRevision <= previous) return;
    cameraRevisions.current.set(incomingPanoramaCamera.viewerId, incomingPanoramaCamera.cameraRevision);
    acceptCamera({
      schema: _streetViewContract__WEBPACK_IMPORTED_MODULE_11__.CAMERA_CONTEXT_SCHEMA,
      editorId: active.editorId,
      sourceFingerprint: active.sourceFingerprint,
      selectionEpoch: active.selectionEpoch,
      selectionRevision: active.selectionRevision,
      tileId: active.tileId,
      viewerId: incomingPanoramaCamera.viewerId,
      imageId: incomingPanoramaCamera.panoId,
      displayRevision: incomingPanoramaCamera.cameraRevision,
      requestRevision: inspection.requestRevision,
      location: incomingPanoramaCamera.actualLocation,
      headingDegrees: incomingPanoramaCamera.headingDegrees,
      headingMeaning: 'live-view-direction'
    });
  }, [incomingPanoramaCamera]);
  var issues = (0,react__WEBPACK_IMPORTED_MODULE_0__.useMemo)(function () {
    return network.features.length && viewBounds ? (0,_sidewalkEditOperations__WEBPACK_IMPORTED_MODULE_6__.validateNetwork)(network, viewBounds) : [];
  }, [network, viewBounds]);
  var topologyWarnings = (0,react__WEBPACK_IMPORTED_MODULE_0__.useMemo)(function () {
    return network.features.length && viewBounds ? (0,_sidewalkTopology__WEBPACK_IMPORTED_MODULE_7__.validateSidewalkTopology)(network, viewBounds) : [];
  }, [network, viewBounds]);
  var endpoints = (0,react__WEBPACK_IMPORTED_MODULE_0__.useMemo)(function () {
    return (0,_sidewalkEditOperations__WEBPACK_IMPORTED_MODULE_6__.networkNodes)(network);
  }, [network]);
  var drawingAnchor = drawing[drawing.length - 1];
  var drawingAnchorIsNetworkNode = drawingAnchor && endpoints.some(function (point) {
    return coordinateKey(point) === coordinateKey(drawingAnchor);
  });
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    if (!sourcesOpen) return;
    var outside = function outside(target) {
      var _sourcesButton$curren, _sourcesPanel$current;
      return target instanceof Node && !((_sourcesButton$curren = sourcesButton.current) !== null && _sourcesButton$curren !== void 0 && _sourcesButton$curren.contains(target)) && !((_sourcesPanel$current = sourcesPanel.current) !== null && _sourcesPanel$current !== void 0 && _sourcesPanel$current.contains(target));
    };
    var onPointerDown = function onPointerDown(event) {
      if (!outside(event.target)) return;
      setSourcesOpen(false);
      setCopyStatus('');
      suppressOutsideClick.current = true;
      event.preventDefault();
      event.stopPropagation();
    };
    var onClick = function onClick(event) {
      if (!suppressOutsideClick.current) return;
      suppressOutsideClick.current = false;
      event.preventDefault();
      event.stopPropagation();
    };
    var onKeyDown = function onKeyDown(event) {
      var _sourcesButton$curren2;
      if (event.key !== 'Escape') return;
      event.preventDefault();
      event.stopPropagation();
      setSourcesOpen(false);
      setCopyStatus('');
      (_sourcesButton$curren2 = sourcesButton.current) === null || _sourcesButton$curren2 === void 0 || _sourcesButton$curren2.focus();
    };
    document.addEventListener('pointerdown', onPointerDown, true);
    document.addEventListener('click', onClick, true);
    document.addEventListener('keydown', onKeyDown, true);
    return function () {
      document.removeEventListener('pointerdown', onPointerDown, true);
      document.removeEventListener('click', onClick, true);
      document.removeEventListener('keydown', onKeyDown, true);
    };
  }, [sourcesOpen]);
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    var generation = ++requestGeneration.current;
    var controller = new AbortController();
    var current = function current() {
      return !controller.signal.aborted && generation === requestGeneration.current;
    };
    setLoading(true);
    setError('');
    setImageReady(false);
    setImageAspect(1);
    setLoadedRequest(null);
    setSelection(null);
    setNetwork(emptyFC);
    setSourceNetwork(emptyFC);
    setBounds(null);
    setTileCrs(null);
    setImageUrl('');
    setPast([]);
    setFuture([]);
    setFutureOperations([]);
    setOperations([]);
    if (pendingDraw.current) clearTimeout(pendingDraw.current.timer);
    pendingDraw.current = null;
    drawingRef.current = [];
    setDrawing([]);
    setDrawingCursor(null);
    setSelectedNode(null);
    setDrag(null);
    setMarqueeStart(null);
    setMarqueeEnd(null);
    dragMoved.current = false;
    Promise.resolve((selectionFeature === null || selectionFeature === void 0 ? void 0 : selectionFeature.type) === 'Feature' && selectionFeature.geometry ? {
      type: 'FeatureCollection',
      features: [selectionFeature]
    } : resolveSelection(input, controller.signal)).then(/*#__PURE__*/function () {
      var _ref0 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee(fc) {
        var _fc$features, _ref10, _selected$features$0$, _selected$features$0$2, _selected$features$0$3, _selected$features$0$4, _selected$features$0$5, _selected$features$0$6, _selected$features$0$7, _selected$features$0$8, _ref11, _ref12, _crs$properties$name, _crs, _configRef$current$ac, _configRef$current$ac2, _saved$originalNetwor, _saved$network, _saved$past, _saved$future, _saved$futureOperatio, _saved$future2, _saved$operations;
        var directFeature, idIndex, index, selected, nextBounds, id, image, networkPath, imageAvailable, declaredCrs, saved, loadedNetwork, _saved$provenance, _saved$operations2, _saved$revision, _saved$committedEdit, _saved$revision2, _saved$operations3, provenance, replay, _t, _t2, _t3;
        return _regenerator().w(function (_context) {
          while (1) switch (_context.n) {
            case 0:
              if (current()) {
                _context.n = 1;
                break;
              }
              return _context.a(2);
            case 1:
              if (fc !== null && fc !== void 0 && (_fc$features = fc.features) !== null && _fc$features !== void 0 && _fc$features.length) {
                _context.n = 2;
                break;
              }
              sendActiveTile(null);
              setLoading(false);
              return _context.a(2);
            case 2:
              directFeature = (selectionFeature === null || selectionFeature === void 0 ? void 0 : selectionFeature.type) === 'Feature' && selectionFeature.geometry ? selectionFeature : null;
              idIndex = selectionFeatureId == null ? -1 : fc.features.findIndex(function (feature) {
                var _ref1, _properties$tile_id;
                var properties = feature.properties;
                var id = (_ref1 = (_properties$tile_id = properties === null || properties === void 0 ? void 0 : properties.tile_id) !== null && _properties$tile_id !== void 0 ? _properties$tile_id : properties === null || properties === void 0 ? void 0 : properties.tileId) !== null && _ref1 !== void 0 ? _ref1 : properties === null || properties === void 0 ? void 0 : properties.id;
                return id != null && String(id) === selectionFeatureId;
              });
              index = directFeature ? 0 : selectionFeatureId != null ? idIndex : selectionIndex == null && allowSingleTile && fc.features.length === 1 ? 0 : selectionIndex;
              if (!(index == null)) {
                _context.n = 3;
                break;
              }
              sendActiveTile(null);
              if (configRef.current.activeSelection) persistConfig(_objectSpread(_objectSpread({}, configRef.current), {}, {
                activeSelection: undefined
              }));
              setLoading(false);
              return _context.a(2);
            case 3:
              if (!(index < 0 || index >= fc.features.length)) {
                _context.n = 4;
                break;
              }
              throw new Error('The selected tile is no longer present. Pick a tile again.');
            case 4:
              selected = {
                type: 'FeatureCollection',
                features: [directFeature !== null && directFeature !== void 0 ? directFeature : fc.features[index]]
              };
              nextBounds = (0,_sidewalkEditOperations__WEBPACK_IMPORTED_MODULE_6__.featureBounds)(selected.features[0]);
              if (nextBounds) {
                _context.n = 5;
                break;
              }
              throw new Error('The selected tile has no polygon bounds.');
            case 5:
              id = String((_ref10 = (_selected$features$0$ = (_selected$features$0$2 = selected.features[0].properties) === null || _selected$features$0$2 === void 0 ? void 0 : _selected$features$0$2.tile_id) !== null && _selected$features$0$ !== void 0 ? _selected$features$0$ : (_selected$features$0$3 = selected.features[0].properties) === null || _selected$features$0$3 === void 0 ? void 0 : _selected$features$0$3.tileId) !== null && _ref10 !== void 0 ? _ref10 : '');
              if (id) {
                _context.n = 6;
                break;
              }
              throw new Error('The selected feature must include a tile_id property.');
            case 6:
              image = (0,_selectedResources__WEBPACK_IMPORTED_MODULE_5__.resolveSelectedResourceTemplate)(String((_selected$features$0$4 = (_selected$features$0$5 = selected.features[0].properties) === null || _selected$features$0$5 === void 0 ? void 0 : _selected$features$0$5.image_url) !== null && _selected$features$0$4 !== void 0 ? _selected$features$0$4 : configRef.current.imageUrlTemplate), selected);
              networkPath = (0,_selectedResources__WEBPACK_IMPORTED_MODULE_5__.resolveSelectedResourceTemplate)(String((_selected$features$0$6 = (_selected$features$0$7 = selected.features[0].properties) === null || _selected$features$0$7 === void 0 ? void 0 : _selected$features$0$7.network_url) !== null && _selected$features$0$6 !== void 0 ? _selected$features$0$6 : configRef.current.networkUrlTemplate), selected);
              imageAvailable = ((_selected$features$0$8 = selected.features[0].properties) === null || _selected$features$0$8 === void 0 ? void 0 : _selected$features$0$8.image_available) !== false;
              declaredCrs = (_ref11 = (_ref12 = (_crs$properties$name = (_crs = fc.crs) === null || _crs === void 0 || (_crs = _crs.properties) === null || _crs === void 0 ? void 0 : _crs.name) !== null && _crs$properties$name !== void 0 ? _crs$properties$name : fc.crs) !== null && _ref12 !== void 0 ? _ref12 : selected.features[0].crs) !== null && _ref11 !== void 0 ? _ref11 : null;
              sendActiveTile(selected.features[0], typeof declaredCrs === 'string' ? declaredCrs : null);
              setSelection(selected);
              setBounds(nextBounds);
              setTileCrs(typeof declaredCrs === 'string' ? declaredCrs : null);
              setImageUrl(imageAvailable ? fileUrl(image) : '');
              setImageReady(!imageAvailable);
              setImageGeneration(generation);
              if (((_configRef$current$ac = configRef.current.activeSelection) === null || _configRef$current$ac === void 0 ? void 0 : _configRef$current$ac.tileId) !== id || ((_configRef$current$ac2 = configRef.current.activeSelection) === null || _configRef$current$ac2 === void 0 ? void 0 : _configRef$current$ac2.sourceFingerprint) !== fingerprint) {
                persistConfig(_objectSpread(_objectSpread({}, configRef.current), {}, {
                  activeSelection: {
                    tileId: id,
                    sourceFingerprint: fingerprint
                  }
                }));
              }
              saved = (0,_overviewData__WEBPACK_IMPORTED_MODULE_10__.savedTile)(configRef.current, id);
              if (!((_saved$originalNetwor = saved === null || saved === void 0 ? void 0 : saved.originalNetwork) !== null && _saved$originalNetwor !== void 0)) {
                _context.n = 7;
                break;
              }
              _t = _saved$originalNetwor;
              _context.n = 11;
              break;
            case 7:
              _t2 = _sidewalkEditOperations__WEBPACK_IMPORTED_MODULE_6__.clipNetworkToBounds;
              if (!(originalNetwork !== null && originalNetwork !== void 0)) {
                _context.n = 8;
                break;
              }
              _t3 = originalNetwork;
              _context.n = 10;
              break;
            case 8:
              _context.n = 9;
              return loadNetwork(networkPath, controller.signal);
            case 9:
              _t3 = _context.v;
            case 10:
              _t = _t2(_t3, nextBounds);
            case 11:
              loadedNetwork = _t;
              if (current()) {
                _context.n = 12;
                break;
              }
              return _context.a(2);
            case 12:
              setSourceNetwork(loadedNetwork);
              setNetwork((_saved$network = saved === null || saved === void 0 ? void 0 : saved.network) !== null && _saved$network !== void 0 ? _saved$network : loadedNetwork);
              setPast((_saved$past = saved === null || saved === void 0 ? void 0 : saved.past) !== null && _saved$past !== void 0 ? _saved$past : []);
              setFuture((_saved$future = saved === null || saved === void 0 ? void 0 : saved.future) !== null && _saved$future !== void 0 ? _saved$future : []);
              setFutureOperations((_saved$futureOperatio = saved === null || saved === void 0 ? void 0 : saved.futureOperations) !== null && _saved$futureOperatio !== void 0 ? _saved$futureOperatio : ((_saved$future2 = saved === null || saved === void 0 ? void 0 : saved.future) !== null && _saved$future2 !== void 0 ? _saved$future2 : []).map(function () {
                return 'redo';
              }));
              setOperations((_saved$operations = saved === null || saved === void 0 ? void 0 : saved.operations) !== null && _saved$operations !== void 0 ? _saved$operations : []);
              setLoadedRequest(request);
              setLoading(false);
              if (saved !== null && saved !== void 0 && saved.committedNetwork) {
                provenance = (_saved$provenance = saved.provenance) !== null && _saved$provenance !== void 0 ? _saved$provenance : (0,_provenance__WEBPACK_IMPORTED_MODULE_9__.buildEditProvenance)({
                  tileId: id,
                  operations: (_saved$operations2 = saved.operations) !== null && _saved$operations2 !== void 0 ? _saved$operations2 : [],
                  before: loadedNetwork,
                  after: saved.committedNetwork,
                  editRevision: (_saved$revision = saved.revision) !== null && _saved$revision !== void 0 ? _saved$revision : 1,
                  validationWarnings: []
                });
                replay = (_saved$committedEdit = saved.committedEdit) !== null && _saved$committedEdit !== void 0 ? _saved$committedEdit : (0,_networkEditContract__WEBPACK_IMPORTED_MODULE_8__.makeNetworkEditEnvelope)({
                  tileId: id,
                  editRevision: (_saved$revision2 = saved.revision) !== null && _saved$revision2 !== void 0 ? _saved$revision2 : 1,
                  operationTypes: (_saved$operations3 = saved.operations) !== null && _saved$operations3 !== void 0 ? _saved$operations3 : [],
                  tileFeature: selected.features[0],
                  before: loadedNetwork,
                  after: saved.committedNetwork,
                  provenance: provenance
                });
                interactionsCallback === null || interactionsCallback === void 0 || interactionsCallback(_defineProperty({}, _networkEditContract__WEBPACK_IMPORTED_MODULE_8__.SIDEWALK_NETWORK_EDIT_CHANNEL, replay), nodeId);
              }
            case 13:
              return _context.a(2);
          }
        }, _callee);
      }));
      return function (_x5) {
        return _ref0.apply(this, arguments);
      };
    }())["catch"](function (e) {
      if (!current()) return;
      sendActiveTile(null);
      setNetwork(emptyFC);
      setSourceNetwork(emptyFC);
      setLoadedRequest(null);
      setError(e instanceof Error ? e.message : String(e));
      setLoading(false);
    });
    return function () {
      controller.abort();
      if (pendingDraw.current) clearTimeout(pendingDraw.current.timer);
      pendingDraw.current = null;
    };
    // Saved code changes must not reload a tile or discard its current draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request]);
  var persistNetwork = (0,react__WEBPACK_IMPORTED_MODULE_0__.useCallback)(function (next, operation) {
    var before = arguments.length > 2 && arguments[2] !== undefined ? arguments[2] : network;
    if (!ready || !tileId || next === before) return;
    var nextPast = [].concat(_toConsumableArray(past.slice(-49)), [before]);
    var nextOps = [].concat(_toConsumableArray(operations), [operation]);
    var saved = _objectSpread(_objectSpread({}, (0,_overviewData__WEBPACK_IMPORTED_MODULE_10__.savedTile)(configRef.current, tileId)), {}, {
      network: next,
      past: nextPast,
      future: [],
      futureOperations: [],
      operations: nextOps
    });
    var nextConfig = _objectSpread(_objectSpread({}, configRef.current), {}, {
      byTile: _objectSpread(_objectSpread({}, configRef.current.byTile), {}, _defineProperty({}, (0,_overviewData__WEBPACK_IMPORTED_MODULE_10__.tileStorageKey)(configRef.current, tileId), saved))
    });
    setNetwork(next);
    setPast(nextPast);
    setFuture([]);
    setFutureOperations([]);
    setOperations(nextOps);
    persistConfig(nextConfig);
  }, [ready, tileId, network, past, future, operations, config, persist]);
  var currentDrawing = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)({
    network: network,
    persistNetwork: persistNetwork
  });
  currentDrawing.current = {
    network: network,
    persistNetwork: persistNetwork
  };
  var undo = function undo() {
    var _operations$at;
    if (!ready || !past.length || !tileId) return;
    var previous = past[past.length - 1];
    var nextPast = past.slice(0, -1);
    var nextFuture = [network].concat(_toConsumableArray(future));
    var nextFutureOperations = [(_operations$at = operations.at(-1)) !== null && _operations$at !== void 0 ? _operations$at : 'edit'].concat(_toConsumableArray(futureOperations));
    var nextOps = operations.slice(0, -1);
    setNetwork(previous);
    setPast(nextPast);
    setFuture(nextFuture);
    setFutureOperations(nextFutureOperations);
    setOperations(nextOps);
    persistConfig(_objectSpread(_objectSpread({}, configRef.current), {}, {
      byTile: _objectSpread(_objectSpread({}, configRef.current.byTile), {}, _defineProperty({}, (0,_overviewData__WEBPACK_IMPORTED_MODULE_10__.tileStorageKey)(configRef.current, tileId), _objectSpread(_objectSpread({}, (0,_overviewData__WEBPACK_IMPORTED_MODULE_10__.savedTile)(configRef.current, tileId)), {}, {
        network: previous,
        past: nextPast,
        future: nextFuture,
        futureOperations: nextFutureOperations,
        operations: nextOps
      })))
    }));
  };
  var redo = function redo() {
    var _futureOperations$;
    if (!ready || !future.length || !tileId) return;
    var next = future[0];
    var nextFuture = future.slice(1);
    var nextFutureOperations = futureOperations.slice(1);
    var nextPast = [].concat(_toConsumableArray(past.slice(-49)), [network]);
    var nextOps = [].concat(_toConsumableArray(operations), [(_futureOperations$ = futureOperations[0]) !== null && _futureOperations$ !== void 0 ? _futureOperations$ : 'redo']);
    setNetwork(next);
    setPast(nextPast);
    setFuture(nextFuture);
    setFutureOperations(nextFutureOperations);
    setOperations(nextOps);
    persistConfig(_objectSpread(_objectSpread({}, configRef.current), {}, {
      byTile: _objectSpread(_objectSpread({}, configRef.current.byTile), {}, _defineProperty({}, (0,_overviewData__WEBPACK_IMPORTED_MODULE_10__.tileStorageKey)(configRef.current, tileId), _objectSpread(_objectSpread({}, (0,_overviewData__WEBPACK_IMPORTED_MODULE_10__.savedTile)(configRef.current, tileId)), {}, {
        network: next,
        past: nextPast,
        future: nextFuture,
        futureOperations: nextFutureOperations,
        operations: nextOps
      })))
    }));
  };
  var svgPoint = function svgPoint(event) {
    return clientToViewPoint(event.currentTarget.getBoundingClientRect(), event.clientX, event.clientY);
  };
  var snapEndpoint = function snapEndpoint(point, exclude) {
    var _imageSvg$current;
    if (!viewBounds) return point;
    var rect = (_imageSvg$current = imageSvg.current) === null || _imageSvg$current === void 0 ? void 0 : _imageSvg$current.getBoundingClientRect();
    if (!(rect !== null && rect !== void 0 && rect.width) || !rect.height) return point;
    // Stewards snaps through rendered node hits. The SVG equivalent is a
    // stable eight CSS-pixel hit radius at the current editor zoom.
    var best = null;
    var distance = 8;
    var _iterator = _createForOfIteratorHelper(endpoints),
      _step;
    try {
      for (_iterator.s(); !(_step = _iterator.n()).done;) {
        var endpoint = _step.value;
        if (exclude && coordinateKey(endpoint) === coordinateKey(exclude)) continue;
        var a = pointToView(endpoint, viewBounds);
        var b = pointToView(point, viewBounds);
        var nextDistance = Math.hypot((a[0] - b[0]) * rect.width / VIEW, (a[1] - b[1]) * rect.height / VIEW);
        if (nextDistance <= distance) {
          best = endpoint;
          distance = nextDistance;
        }
      }
    } catch (err) {
      _iterator.e(err);
    } finally {
      _iterator.f();
    }
    return best !== null && best !== void 0 ? best : point;
  };
  var pointerDown = function pointerDown(event) {
    if (!viewBounds) return;
    // Read the native event before scheduling React state updates. React clears
    // `currentTarget` after dispatch; reading it inside a functional updater can
    // therefore throw `getBoundingClientRect` on null.
    var point = svgPoint(event);
    if (mode === 'delete-area') {
      setMarqueeStart(point);
      setMarqueeEnd(point);
      event.currentTarget.setPointerCapture(event.pointerId);
    }
  };
  var pointerMove = function pointerMove(event) {
    if (marqueeStart) setMarqueeEnd(svgPoint(event));
    if (mode === 'draw' && drawing.length && viewBounds) {
      var _svgPoint = svgPoint(event),
        _svgPoint2 = _slicedToArray(_svgPoint, 2),
        x = _svgPoint2[0],
        y = _svgPoint2[1];
      setDrawingCursor(snapEndpoint(viewToPoint(x, y, viewBounds)));
    }
    if (drag && viewBounds) {
      var _svgPoint3 = svgPoint(event),
        _svgPoint4 = _slicedToArray(_svgPoint3, 2),
        _x6 = _svgPoint4[0],
        _y = _svgPoint4[1];
      var target = snapEndpoint(viewToPoint(_x6, _y, viewBounds), drag.from);
      if (Math.hypot(target[0] - drag.from[0], target[1] - drag.from[1]) > 1e-10) dragMoved.current = true;
      setSelectedNode(target);
      setNetwork((0,_sidewalkEditOperations__WEBPACK_IMPORTED_MODULE_6__.moveNetworkNode)(drag.original, drag.from, target));
    }
  };
  var pointerUp = function pointerUp() {
    if (marqueeStart && marqueeEnd && viewBounds) {
      var _imageSvg$current2, _rect$width, _rect$height;
      var rect = (_imageSvg$current2 = imageSvg.current) === null || _imageSvg$current2 === void 0 ? void 0 : _imageSvg$current2.getBoundingClientRect();
      var dx = Math.abs(marqueeStart[0] - marqueeEnd[0]) * ((_rect$width = rect === null || rect === void 0 ? void 0 : rect.width) !== null && _rect$width !== void 0 ? _rect$width : VIEW) / VIEW;
      var dy = Math.abs(marqueeStart[1] - marqueeEnd[1]) * ((_rect$height = rect === null || rect === void 0 ? void 0 : rect.height) !== null && _rect$height !== void 0 ? _rect$height : VIEW) / VIEW;
      if (Math.hypot(dx, dy) >= 3) {
        var a = viewToPoint.apply(void 0, _toConsumableArray(marqueeStart).concat([viewBounds]));
        var b = viewToPoint.apply(void 0, _toConsumableArray(marqueeEnd).concat([viewBounds]));
        persistNetwork((0,_sidewalkEditOperations__WEBPACK_IMPORTED_MODULE_6__.deleteNetworkNodesInBounds)(network, [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])]), 'delete_nodes_in_area');
      }
    }
    if (drag && !marqueeStart && dragMoved.current) persistNetwork(network, 'move_node', drag.original);
    dragMoved.current = false;
    setMarqueeStart(null);
    setMarqueeEnd(null);
    setDrag(null);
  };
  var pointerCancel = function pointerCancel() {
    if (drag) setNetwork(drag.original);
    dragMoved.current = false;
    setDrag(null);
    setMarqueeStart(null);
    setMarqueeEnd(null);
    setSelectedNode(null);
  };
  var onNodePointerDown = function onNodePointerDown(event, p) {
    event.stopPropagation();
    if (mode === 'select' || mode === 'move') {
      setSelectedNode(p);
      var edgeTolerance = viewBounds ? Math.min(viewBounds[2] - viewBounds[0], viewBounds[3] - viewBounds[1]) * 1e-7 : 0;
      var boundary = viewBounds && (Math.abs(p[0] - viewBounds[0]) <= edgeTolerance || Math.abs(p[0] - viewBounds[2]) <= edgeTolerance || Math.abs(p[1] - viewBounds[1]) <= edgeTolerance || Math.abs(p[1] - viewBounds[3]) <= edgeTolerance);
      if (boundary) {
        setMovementNotice('Tile-boundary nodes cannot be moved until cross-tile editing is supported.');
        return;
      }
      setMovementNotice('');
      dragMoved.current = false;
      setDrag({
        from: p,
        pointer: event.pointerId,
        original: network
      });
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    if (mode === 'delete-area') return;
  };
  var deleteSelectedNode = function deleteSelectedNode() {
    if (selectedNode) {
      persistNetwork((0,_sidewalkEditOperations__WEBPACK_IMPORTED_MODULE_6__.deleteNetworkNode)(network, selectedNode), 'delete_node_and_incident_edges');
      setSelectedNode(null);
    }
  };
  var onDrawClick = function onDrawClick(event) {
    var _currentActiveTile$cu;
    if (mode === 'inspect' && ready && viewBounds && (_currentActiveTile$cu = currentActiveTile.current) !== null && _currentActiveTile$cu !== void 0 && _currentActiveTile$cu.tileId) {
      event.preventDefault();
      event.stopPropagation();
      try {
        var _callbackRef$current5;
        var location = (0,_streetViewContract__WEBPACK_IMPORTED_MODULE_11__.pointToWgs84)(viewToPoint.apply(void 0, _toConsumableArray(svgPoint(event)).concat([viewBounds])), tileCrs);
        var active = currentActiveTile.current;
        var next = {
          schema: _streetViewContract__WEBPACK_IMPORTED_MODULE_11__.INSPECTION_REQUEST_SCHEMA,
          editorId: active.editorId,
          sourceFingerprint: active.sourceFingerprint,
          selectionEpoch: active.selectionEpoch,
          selectionRevision: active.selectionRevision,
          requestRevision: ++inspectionRevision.current,
          tileId: active.tileId,
          location: location,
          crs: 'EPSG:4326'
        };
        currentInspection.current = next;
        setRequestedPoint(location);
        setInspectionStatus(null);
        setCamera(null);
        accumulatedHeading.current = null;
        setDisplayHeading(null);
        cameraRevisions.current.clear();
        // Carry the current tile with each inspection. Interaction delivery is
        // event based, so a viewer attached after restoration may have missed
        // the earlier active-tile announcement.
        (_callbackRef$current5 = callbackRef.current) === null || _callbackRef$current5 === void 0 || _callbackRef$current5.call(callbackRef, _defineProperty(_defineProperty(_defineProperty({}, _streetViewContract__WEBPACK_IMPORTED_MODULE_11__.ACTIVE_TILE_CHANNEL, active), _streetViewContract__WEBPACK_IMPORTED_MODULE_11__.INSPECTION_REQUEST_CHANNEL, next), _curio_streetvision_1_sources_panoramaContract__WEBPACK_IMPORTED_MODULE_17__.PANORAMA_REQUEST_CHANNEL, panoramaRequestForInspection(next)), nodeId);
      } catch (error) {
        setStatus({
          code: 'error',
          content: error instanceof Error ? error.message : String(error)
        });
      }
      return;
    }
    if (mode !== 'draw' || !viewBounds) return;
    var screen = svgPoint(event);
    var click = {
      point: snapEndpoint(viewToPoint.apply(void 0, _toConsumableArray(screen).concat([viewBounds]))),
      screen: screen
    };
    var commit = function commit(clicks) {
      var _iterator2 = _createForOfIteratorHelper(clicks),
        _step2;
      try {
        for (_iterator2.s(); !(_step2 = _iterator2.n()).done;) {
          var point = _step2.value.point;
          var previous = drawingRef.current.at(-1);
          if (previous && coordinateKey(previous) === coordinateKey(point)) continue;
          if (previous) {
            var before = currentDrawing.current.network;
            var _next2 = (0,_sidewalkEditOperations__WEBPACK_IMPORTED_MODULE_6__.connectNetworkNodes)(before, previous, point);
            if (_next2 !== before) {
              currentDrawing.current.network = _next2;
              currentDrawing.current.persistNetwork(_next2, 'draw_edge', before);
            }
          }
          drawingRef.current = [].concat(_toConsumableArray(drawingRef.current), [point]);
          setDrawing(drawingRef.current);
          setDrawingCursor(null);
        }
      } catch (err) {
        _iterator2.e(err);
      } finally {
        _iterator2.f();
      }
    };
    var arm = function arm(clicks) {
      var timer = setTimeout(function () {
        pendingDraw.current = null;
        commit(clicks);
      }, 220);
      pendingDraw.current = {
        clicks: clicks,
        timer: timer
      };
    };
    var pending = pendingDraw.current;
    if (pending) {
      clearTimeout(pending.timer);
      var last = pending.clicks.at(-1);
      if (Math.hypot(last.screen[0] - screen[0], last.screen[1] - screen[1]) < 8) {
        arm([].concat(_toConsumableArray(pending.clicks), [click]));
        return;
      }
      pendingDraw.current = null;
      commit(pending.clicks);
    }
    arm([click]);
  };
  var endDrawChain = function endDrawChain(event) {
    if (mode !== 'draw') return;
    event.preventDefault();
    if (pendingDraw.current) clearTimeout(pendingDraw.current.timer);
    pendingDraw.current = null;
    drawingRef.current = [];
    setDrawing([]);
    setDrawingCursor(null);
  };
  var splitAt = function splitAt(event) {
    if (!viewBounds || mode !== 'select' || event.button !== 2) return;
    event.preventDefault();
    var rect = event.currentTarget.getBoundingClientRect();
    var p = viewToPoint((event.clientX - rect.left) / rect.width * VIEW, (event.clientY - rect.top) / rect.height * VIEW, viewBounds);
    var nearest = closestLineSegment(network, p);
    var tolerance = Math.max(viewBounds[2] - viewBounds[0], viewBounds[3] - viewBounds[1]) * 0.02;
    if (nearest && nearest.distance <= tolerance) persistNetwork((0,_sidewalkEditOperations__WEBPACK_IMPORTED_MODULE_6__.splitNetworkEdge)(network, nearest.featureIndex, nearest.segmentIndex, nearest.point), 'split_edge');
  };
  var saveNetwork = function saveNetwork() {
    var _savedTile$revision, _savedTile;
    if (!ready || !viewBounds || !tileId) return;
    if (issues.length) {
      setStatus({
        code: 'error',
        content: issues.join(' ')
      });
      return;
    }
    if (!tileFeature) return;
    var correctedNetwork = (0,_sidewalkEditOperations__WEBPACK_IMPORTED_MODULE_6__.clipNetworkToBounds)(network, viewBounds);
    var revision = ((_savedTile$revision = (_savedTile = (0,_overviewData__WEBPACK_IMPORTED_MODULE_10__.savedTile)(configRef.current, tileId)) === null || _savedTile === void 0 ? void 0 : _savedTile.revision) !== null && _savedTile$revision !== void 0 ? _savedTile$revision : 0) + 1;
    var provenance = (0,_provenance__WEBPACK_IMPORTED_MODULE_9__.buildEditProvenance)({
      tileId: tileId,
      operations: operations,
      before: sourceNetwork,
      after: correctedNetwork,
      editRevision: revision,
      validationWarnings: topologyWarnings.map(function (warning) {
        return warning.message;
      })
    });
    var commit = (0,_networkEditContract__WEBPACK_IMPORTED_MODULE_8__.makeNetworkEditEnvelope)({
      tileId: tileId,
      editRevision: revision,
      operationTypes: _toConsumableArray(operations),
      tileFeature: tileFeature,
      before: sourceNetwork,
      after: correctedNetwork,
      provenance: provenance
    });
    var saved = _objectSpread(_objectSpread({}, (0,_overviewData__WEBPACK_IMPORTED_MODULE_10__.savedTile)(configRef.current, tileId)), {}, {
      network: network,
      originalNetwork: sourceNetwork,
      past: past,
      future: future,
      futureOperations: futureOperations,
      operations: operations,
      revision: revision,
      committedNetwork: correctedNetwork,
      provenance: provenance,
      committedEdit: commit
    });
    var nextConfig = _objectSpread(_objectSpread({}, configRef.current), {}, {
      byTile: _objectSpread(_objectSpread({}, configRef.current.byTile), {}, _defineProperty({}, (0,_overviewData__WEBPACK_IMPORTED_MODULE_10__.tileStorageKey)(configRef.current, tileId), saved))
    });
    persistConfig(nextConfig);
    if (configRef.current.mode !== 'input-overview') interactionsCallback === null || interactionsCallback === void 0 || interactionsCallback(_defineProperty({}, _networkEditContract__WEBPACK_IMPORTED_MODULE_8__.SIDEWALK_NETWORK_EDIT_CHANNEL, commit), nodeId);
    var output = _objectSpread(_objectSpread({}, correctedNetwork), {}, {
      metadata: {
        sidewalkTileId: tileId,
        editRevision: revision,
        schema: SIDEWALK_EDIT_SCHEMA,
        operationCount: operations.length,
        topologyWarnings: topologyWarnings.map(function (warning) {
          return warning.code;
        }),
        provenance: provenance
      }
    });
    var latestOutput = {
      data: output,
      dataType: 'geodataframe'
    };
    if (onCommitted) onCommitted(nextConfig, latestOutput);else emit(latestOutput);
    setStatus({
      code: 'success',
      content: "Applied network revision ".concat(revision, " for tile ").concat(tileId, " and sent it downstream.").concat(topologyWarnings.length ? " Review ".concat(topologyWarnings.length, " topology warning(s).") : '')
    });
  };
  var selectedResource = function selectedResource(value, fallback) {
    return tileFeature ? (0,_selectedResources__WEBPACK_IMPORTED_MODULE_5__.resolveSelectedResourceTemplate)(String(value !== null && value !== void 0 ? value : fallback), selection) : fallback;
  };
  var imageSource = selectedResource(tileFeature === null || tileFeature === void 0 || (_tileFeature$properti4 = tileFeature.properties) === null || _tileFeature$properti4 === void 0 ? void 0 : _tileFeature$properti4.image_url, config.imageUrlTemplate);
  var networkSource = originalNetwork ? ((_config$overview2 = config.overview) === null || _config$overview2 === void 0 ? void 0 : _config$overview2.networkUrl) || 'Connected upstream network' : selectedResource(tileFeature === null || tileFeature === void 0 || (_tileFeature$properti5 = tileFeature.properties) === null || _tileFeature$properti5 === void 0 ? void 0 : _tileFeature$properti5.network_url, config.networkUrlTemplate);
  var copySource = function copySource(label, value) {
    var _navigator$clipboard;
    if (!((_navigator$clipboard = navigator.clipboard) !== null && _navigator$clipboard !== void 0 && _navigator$clipboard.writeText)) return;
    void navigator.clipboard.writeText(value).then(function () {
      return setCopyStatus("".concat(label, " copied"));
    })["catch"](function () {
      return setCopyStatus('Copy unavailable in this browser');
    });
  };
  var activateMode = function activateMode(next) {
    setMode(function (current) {
      return current === next ? 'select' : next;
    });
    if (pendingDraw.current) clearTimeout(pendingDraw.current.timer);
    pendingDraw.current = null;
    drawingRef.current = [];
    setDrawing([]);
    setDrawingCursor(null);
    setSelectedNode(null);
    setDrag(null);
    setMarqueeStart(null);
    setMarqueeEnd(null);
    dragMoved.current = false;
  };
  var onKeyDown = function onKeyDown(event) {
    if (!ready) return;
    var target = event.target;
    if (target instanceof Element && target.closest('input, textarea, select, [contenteditable="true"]')) return;
    if (event.key === 'Escape') {
      if (pendingDraw.current) clearTimeout(pendingDraw.current.timer);
      pendingDraw.current = null;
      drawingRef.current = [];
      if (drag) setNetwork(drag.original);
      setMode('select');
      setDrawing([]);
      setDrawingCursor(null);
      setMarqueeStart(null);
      setMarqueeEnd(null);
      setDrag(null);
      setSelectedNode(null);
      dragMoved.current = false;
      return;
    }
    if ((event.key === 'Delete' || event.key === 'Backspace') && selectedNode && mode === 'select') {
      event.preventDefault();
      deleteSelectedNode();
      return;
    }
    var key = event.key.toLowerCase();
    if (key === 'l') {
      activateMode('draw');
      return;
    }
    if (key === 'm') {
      activateMode('move');
      return;
    }
    if (key === 'd') {
      activateMode('delete-area');
      return;
    }
    if (key === 'i') {
      activateMode('inspect');
      return;
    }
    if (!(event.metaKey || event.ctrlKey)) return;
    if (key === 'z') {
      event.preventDefault();
      if (event.shiftKey) redo();else undo();
    } else if (key === 'y') {
      event.preventDefault();
      redo();
    }
  };
  var cameraPoint = camera !== null && camera !== void 0 && camera.location && viewBounds && (_currentActiveTile$cu2 = currentActiveTile.current) !== null && _currentActiveTile$cu2 !== void 0 && _currentActiveTile$cu2.geometry ? pointToView((0,_streetViewContract__WEBPACK_IMPORTED_MODULE_11__.pointFromWgs84)(camera.location, tileCrs), viewBounds) : null;
  var cameraInside = !!cameraPoint && !!((_currentActiveTile$cu3 = currentActiveTile.current) !== null && _currentActiveTile$cu3 !== void 0 && _currentActiveTile$cu3.geometry) && (0,_streetViewImages__WEBPACK_IMPORTED_MODULE_12__.pointInPolygon)(camera.location, currentActiveTile.current.geometry);
  var outside = camera !== null && camera !== void 0 && camera.location && (_currentActiveTile$cu4 = currentActiveTile.current) !== null && _currentActiveTile$cu4 !== void 0 && _currentActiveTile$cu4.geometry && !cameraInside ? (0,_cameraBoundary__WEBPACK_IMPORTED_MODULE_13__.cameraBoundary)(camera.location, currentActiveTile.current.geometry) : null;
  var cuePoint = outside && viewBounds && camera !== null && camera !== void 0 && camera.location ? function () {
    var nearest = pointToView((0,_streetViewContract__WEBPACK_IMPORTED_MODULE_11__.pointFromWgs84)(outside.nearest, tileCrs), viewBounds);
    var raw = cameraPoint !== null && cameraPoint !== void 0 ? cameraPoint : nearest;
    var dx = raw[0] - nearest[0],
      dy = raw[1] - nearest[1];
    var scale = 18 / (Math.hypot(dx, dy) || 1);
    return [nearest[0] + dx * scale, nearest[1] + dy * scale];
  }() : null;
  var markerPoint = cameraInside ? cameraPoint : null;
  var pendingPoint = requestedPoint && !camera && viewBounds && (_currentActiveTile$cu5 = currentActiveTile.current) !== null && _currentActiveTile$cu5 !== void 0 && _currentActiveTile$cu5.geometry && (0,_streetViewImages__WEBPACK_IMPORTED_MODULE_12__.pointInPolygon)(requestedPoint, currentActiveTile.current.geometry) ? pointToView((0,_streetViewContract__WEBPACK_IMPORTED_MODULE_11__.pointFromWgs84)(requestedPoint, tileCrs), viewBounds) : null;
  var pendingMarkerPoint = pendingPoint ? [Math.max(STEWARDS_CAMERA_SIZE / 2, Math.min(VIEW - STEWARDS_CAMERA_SIZE / 2, pendingPoint[0])), Math.max(STEWARDS_CAMERA_SIZE * markerAspect / 2, Math.min(VIEW - STEWARDS_CAMERA_SIZE * markerAspect / 2, pendingPoint[1]))] : null;
  var outsideTagPoint = cuePoint ? [Math.max(CAMERA_CUE_MARGIN, Math.min(VIEW - CAMERA_CUE_MARGIN, cuePoint[0])), Math.max(CAMERA_CUE_MARGIN * markerAspect, Math.min(VIEW - CAMERA_CUE_MARGIN * markerAspect, cuePoint[1]))] : null;
  var outsideTagX = outsideTagPoint ? Math.max(8, Math.min(VIEW - OUTSIDE_CAMERA_TAG_WIDTH - 8, outsideTagPoint[0] + (outsideTagPoint[0] > VIEW / 2 ? -OUTSIDE_CAMERA_TAG_WIDTH - 26 : 26))) - outsideTagPoint[0] : 0;
  var outsideTagY = outsideTagPoint ? Math.max(8, Math.min(VIEW - OUTSIDE_CAMERA_TAG_HEIGHT * markerAspect - 8, outsideTagPoint[1] + (outsideTagPoint[1] > VIEW / 2 ? -OUTSIDE_CAMERA_TAG_HEIGHT - 18 : 18) * markerAspect)) - outsideTagPoint[1] : 0;
  var cameraTileId = camera !== null && camera !== void 0 && camera.location && neighborIndex ? (0,_tileNeighbors__WEBPACK_IMPORTED_MODULE_14__.tileAtPoint)(neighborIndex, camera.location) : null;
  var openCameraTile = function openCameraTile() {
    if (!ready || !(camera !== null && camera !== void 0 && camera.location) || !cameraTileId || cameraTileId === tileId || !onNavigate) return;
    var inspection = currentInspection.current;
    if (!inspection) return;
    pendingCameraAdoption.current = {
      tileId: cameraTileId,
      camera: camera,
      requestId: panoramaRequestForInspection(inspection).requestId,
      revision: inspection.requestRevision,
      cameraRevision: camera.displayRevision
    };
    setNavigationTarget(cameraTileId);
    onNavigate(cameraTileId);
  };
  var navigate = function navigate(direction) {
    var _neighborIndex$neighb;
    var destination = neighborIndex === null || neighborIndex === void 0 || (_neighborIndex$neighb = neighborIndex.neighbors.get(tileId)) === null || _neighborIndex$neighb === void 0 ? void 0 : _neighborIndex$neighb[direction];
    if (!ready || navigationTarget || !destination || !onNavigate) return;
    setNavigationTarget(destination);
    onNavigate(destination);
  };
  var disabledButtonStyle = {
    background: 'var(--curio-surface-muted)',
    border: '1px solid var(--curio-border)',
    color: 'var(--curio-text-secondary)',
    cursor: 'default'
  };
  var toolbarButtonStyle = _objectSpread(_objectSpread({}, _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.button), {}, {
    borderRadius: 'var(--curio-radius-sm)'
  });
  var toolbarSelectedStyle = _objectSpread(_objectSpread({}, toolbarButtonStyle), {}, {
    background: 'var(--curio-accent-sky-bg)',
    border: '1px solid var(--curio-accent-sky-fg)',
    color: 'var(--curio-accent-sky-fg)'
  });
  var deleteButtonStyle = mode === 'delete-area' ? _objectSpread(_objectSpread({}, toolbarSelectedStyle), {}, {
    background: 'var(--curio-danger-text)',
    borderColor: 'var(--curio-danger-text)',
    color: '#fff'
  }) : _objectSpread(_objectSpread({}, toolbarButtonStyle), {}, {
    background: 'var(--curio-danger-bg)',
    borderColor: 'var(--curio-danger-border)',
    color: 'var(--curio-danger-text)'
  });
  return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    className: "nodrag nopan nowheel",
    "data-curio-sidewalk-editor": nodeId,
    role: "region",
    "aria-label": "Sidewalk editor ".concat(nodeId),
    tabIndex: 0,
    onKeyDown: onKeyDown,
    onPointerDownCapture: function onPointerDownCapture(event) {
      if (event.target instanceof Element && !event.target.closest('button, input, textarea, select, [contenteditable="true"], [data-sidewalk-sources-overlay]')) event.currentTarget.focus();
    },
    onBlurCapture: function onBlurCapture(event) {
      if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) {
        if (drag) setNetwork(drag.original);
        if (pendingDraw.current) clearTimeout(pendingDraw.current.timer);
        pendingDraw.current = null;
        drawingRef.current = [];
        setDrawing([]);
        setDrawingCursor(null);
        setSelectedNode(null);
        setDrag(null);
        setMarqueeStart(null);
        setMarqueeEnd(null);
        dragMoved.current = false;
      }
    },
    style: _objectSpread(_objectSpread({}, _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.body), {}, {
      overflowY: 'auto'
    })
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: _objectSpread(_objectSpread({}, _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.row), {}, {
      justifyContent: 'space-between',
      gap: 6
    })
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
    style: {
      minWidth: 0,
      flex: '1 1 220px'
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
    "aria-hidden": "true",
    style: {
      display: 'inline-block',
      width: 9,
      height: 9,
      borderRadius: '50%',
      marginRight: 8,
      background: error ? 'var(--curio-danger-text)' : loading ? 'var(--curio-warning-text)' : ready ? 'var(--curio-success-text)' : 'var(--curio-text-muted)'
    }
  }), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("strong", null, tileId ? "Tile ".concat(tileId) : 'Waiting for tile selection'), ' · ', loading ? 'Loading resources' : error ? 'Resource loading failed' : ready ? imageUrl ? network.features.length ? 'Imagery and network loaded' : 'Imagery and empty network loaded' : 'Network loaded · imagery unavailable' : 'Waiting for resources'), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      display: 'flex',
      gap: 6,
      alignItems: 'center',
      flex: '0 1 auto',
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
    role: "status",
    style: _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.status
  }, operations.length ? "".concat(operations.length, " draft changes") : 'No draft changes'), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    type: "button",
    onClick: saveNetwork,
    disabled: !ready || issues.length > 0,
    style: _objectSpread(_objectSpread({}, _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.primaryButton), {}, {
      borderRadius: 'var(--curio-radius-sm)'
    }, !ready || issues.length > 0 ? disabledButtonStyle : {})
  }, "Save network"))), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("style", null, "[data-curio-sidewalk-editor=\"".concat(nodeId, "\"] .sidewalk-edit-toolbar { container-type: inline-size; }\n        [data-curio-sidewalk-editor=\"").concat(nodeId, "\"] .sidewalk-edit-toolbar-inner { display: flex; align-items: center; gap: 4px; }\n        [data-curio-sidewalk-editor=\"").concat(nodeId, "\"] .sidewalk-edit-toolbar button { display: inline-flex; align-items: center; justify-content: center; gap: 4px; height: 32px; min-height: 32px; box-sizing: border-box; white-space: nowrap; border-radius: var(--curio-radius-sm); flex: none; }\n        [data-curio-sidewalk-editor=\"").concat(nodeId, "\"] .sidewalk-edit-toolbar button svg { width: 16px; height: 16px; flex: none; }\n        [data-curio-sidewalk-editor=\"").concat(nodeId, "\"] .sidewalk-edit-toolbar button:focus-visible { outline: 2px solid var(--curio-top-bar-bg); outline-offset: 2px; }\n        [data-curio-sidewalk-editor=\"").concat(nodeId, "\"] .sidewalk-edit-toolbar button:not(:disabled):hover { filter: brightness(0.94); }\n        [data-curio-sidewalk-editor=\"").concat(nodeId, "\"] .sidewalk-edit-toolbar .sidewalk-mode-command { flex: 1 1 0; min-width: 0; }\n        [data-curio-sidewalk-editor=\"").concat(nodeId, "\"] .sidewalk-edit-toolbar .sidewalk-icon-command { width: 32px; padding: 0; }\n        @container (max-width: 500px) { [data-curio-sidewalk-editor=\"").concat(nodeId, "\"] .sidewalk-edit-toolbar-inner { display: grid; grid-template-columns: max-content max-content max-content; justify-content: start; row-gap: 4px; }\n          [data-curio-sidewalk-editor=\"").concat(nodeId, "\"] .sidewalk-edit-toolbar .sidewalk-edit-command-group { grid-column: 2 / 4; justify-self: end; } }\n        @container (max-width: 350px) { [data-curio-sidewalk-editor=\"").concat(nodeId, "\"] .sidewalk-edit-toolbar-inner { grid-template-columns: max-content max-content; }\n          [data-curio-sidewalk-editor=\"").concat(nodeId, "\"] .sidewalk-edit-toolbar .sidewalk-edit-command-group { grid-column: auto; justify-self: start; } }")), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    role: "toolbar",
    "aria-label": "Sidewalk network editing tools",
    className: "sidewalk-edit-toolbar",
    style: _objectSpread(_objectSpread({}, _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.panel), {}, {
      padding: 4
    }),
    onPointerDown: function onPointerDown(event) {
      return event.stopPropagation();
    },
    onClick: function onClick(event) {
      return event.stopPropagation();
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    className: "sidewalk-edit-toolbar-inner"
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    type: "button",
    className: "sidewalk-mode-command",
    "aria-label": mode === 'inspect' ? 'Exit Street View inspection' : 'Inspect Street View',
    title: "Inspect Street View at a point (I)",
    "aria-pressed": mode === 'inspect',
    disabled: !ready,
    onClick: function onClick() {
      return activateMode('inspect');
    },
    style: _objectSpread(_objectSpread({}, toolbarButtonStyle), mode === 'inspect' ? toolbarSelectedStyle : {})
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement(EditToolIcon, {
    name: "inspect"
  }), " Inspect Street View"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    type: "button",
    className: "sidewalk-mode-command",
    "aria-label": mode === 'draw' ? 'Cancel edge drawing' : 'Draw edges',
    title: "Draw edges (L)",
    "aria-pressed": mode === 'draw',
    disabled: !ready,
    onClick: function onClick() {
      return activateMode('draw');
    },
    style: _objectSpread(_objectSpread({}, toolbarButtonStyle), mode === 'draw' ? toolbarSelectedStyle : {})
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement(EditToolIcon, {
    name: "draw"
  }), " Draw edges"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    type: "button",
    className: "sidewalk-mode-command",
    "aria-label": "Move nodes",
    title: "Drag a node to reposition it (M)",
    "aria-pressed": mode === 'move',
    disabled: !ready,
    onClick: function onClick() {
      return activateMode('move');
    },
    style: _objectSpread(_objectSpread({}, toolbarButtonStyle), mode === 'move' ? toolbarSelectedStyle : {})
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement(EditToolIcon, {
    name: "move"
  }), " Move nodes"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    role: "group",
    "aria-label": "Delete and history",
    className: "sidewalk-edit-command-group",
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 4
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    type: "button",
    className: "sidewalk-icon-command",
    "aria-label": "Delete",
    title: "Delete nodes in an area (D)",
    "aria-pressed": mode === 'delete-area',
    disabled: !ready,
    onClick: function onClick() {
      return activateMode('delete-area');
    },
    style: deleteButtonStyle
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement(EditToolIcon, {
    name: "delete"
  })), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    type: "button",
    className: "sidewalk-icon-command",
    "aria-label": "Undo",
    title: "Undo (Ctrl/Cmd+Z)",
    disabled: !ready || !past.length,
    onClick: undo,
    style: _objectSpread(_objectSpread({}, toolbarButtonStyle), !ready || !past.length ? disabledButtonStyle : {})
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement(EditToolIcon, {
    name: "undo"
  })), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    type: "button",
    className: "sidewalk-icon-command",
    "aria-label": "Redo",
    title: "Redo (Ctrl/Cmd+Y or Shift+Z)",
    disabled: !ready || !future.length,
    onClick: redo,
    style: _objectSpread(_objectSpread({}, toolbarButtonStyle), !ready || !future.length ? disabledButtonStyle : {})
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement(EditToolIcon, {
    name: "redo"
  }))))), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.helper
  }, mode === 'inspect' ? 'Click a location to open Street View.' : mode === 'draw' ? 'Click nodes or the image to draw connected edges; double-click to finish.' : mode === 'move' ? 'Drag a node to reposition it.' : mode === 'delete-area' ? 'Drag a rectangle to delete nodes and incident edges.' : 'Choose a tool to edit the network, or select a node.'), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      flex: 'none',
      boxSizing: 'border-box',
      width: '100%',
      minHeight: 240,
      aspectRatio: imageAspect,
      position: 'relative',
      margin: '4px 0 2px',
      overflow: 'visible',
      background: 'var(--curio-surface-muted)',
      border: '1px solid var(--curio-border)',
      borderRadius: 'var(--curio-radius-md)'
    }
  }, imageUrl && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("img", {
    key: imageGeneration,
    src: imageUrl,
    onLoad: function onLoad(event) {
      if (imageGeneration === requestGeneration.current) {
        var _event$currentTarget = event.currentTarget,
          naturalWidth = _event$currentTarget.naturalWidth,
          naturalHeight = _event$currentTarget.naturalHeight;
        if (naturalWidth > 0 && naturalHeight > 0) setImageAspect(naturalWidth / naturalHeight);
        setImageReady(true);
      }
    },
    onError: function onError() {
      if (imageGeneration === requestGeneration.current) {
        setImageReady(false);
        setError('Tile image could not be loaded. Select another tile or check the image path.');
      }
    },
    alt: "Satellite image for tile ".concat(tileId),
    draggable: false,
    style: {
      position: 'absolute',
      inset: 0,
      width: '100%',
      height: '100%',
      objectFit: 'fill',
      pointerEvents: 'none',
      borderRadius: 'var(--curio-radius-md)'
    }
  }), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    ref: sourcesButton,
    type: "button",
    "aria-label": "Data sources",
    title: "Data sources",
    "aria-expanded": sourcesOpen,
    "aria-controls": "sidewalk-sources-".concat(nodeId),
    onPointerDown: function onPointerDown(event) {
      return event.stopPropagation();
    },
    onClick: function onClick(event) {
      event.stopPropagation();
      setCopyStatus('');
      setSourcesOpen(function (value) {
        return !value;
      });
    },
    style: {
      position: 'absolute',
      zIndex: 8,
      top: 8,
      right: 8,
      width: 40,
      height: 40,
      padding: 0,
      border: 'none',
      background: 'transparent',
      color: '#000000',
      fontSize: 25,
      cursor: 'pointer',
      display: 'grid',
      placeItems: 'center'
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement(CurioUtilityIcon, {
    name: "circle-info"
  })), sourcesOpen && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    ref: sourcesPanel,
    id: "sidewalk-sources-".concat(nodeId),
    "data-sidewalk-sources-overlay": "true",
    role: "dialog",
    "aria-label": "Data sources",
    onPointerDown: function onPointerDown(event) {
      return event.stopPropagation();
    },
    onPointerMove: function onPointerMove(event) {
      return event.stopPropagation();
    },
    onPointerUp: function onPointerUp(event) {
      return event.stopPropagation();
    },
    onClick: function onClick(event) {
      return event.stopPropagation();
    },
    onDoubleClick: function onDoubleClick(event) {
      return event.stopPropagation();
    },
    onContextMenu: function onContextMenu(event) {
      return event.stopPropagation();
    },
    onKeyDown: function onKeyDown(event) {
      return event.stopPropagation();
    },
    style: _objectSpread(_objectSpread({}, _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.panel), {}, {
      position: 'absolute',
      zIndex: 7,
      top: 48,
      right: 8,
      boxSizing: 'border-box',
      width: 'min(330px, calc(100% - 16px))',
      maxHeight: 'min(310px, calc(100% - 56px))',
      overflowY: 'auto',
      padding: '6px 10px 10px',
      background: 'var(--curio-card-bg)',
      boxShadow: '0 4px 16px rgba(15,23,42,0.2)'
    })
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: _objectSpread(_objectSpread({}, _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.row), {}, {
      justifyContent: 'space-between'
    })
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("strong", null, "Data sources"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    type: "button",
    "aria-label": "Close data sources",
    title: "Close data sources",
    onClick: function onClick() {
      var _sourcesButton$curren3;
      setSourcesOpen(false);
      setCopyStatus('');
      (_sourcesButton$curren3 = sourcesButton.current) === null || _sourcesButton$curren3 === void 0 || _sourcesButton$curren3.focus();
    },
    style: {
      border: 'none',
      background: 'none',
      color: 'var(--curio-text-primary)',
      padding: 0,
      width: 28,
      height: 28,
      fontSize: 12,
      lineHeight: 1,
      display: 'grid',
      placeItems: 'center',
      cursor: 'pointer'
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement(CurioUtilityIcon, {
    name: "close"
  }))), [['Image', imageSource], ['Network', networkSource]].map(function (_ref13) {
    var _navigator$clipboard2, _navigator$clipboard3;
    var _ref14 = _slicedToArray(_ref13, 2),
      label = _ref14[0],
      value = _ref14[1];
    return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      key: label,
      style: {
        marginTop: 7
      }
    }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("strong", null, label), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      style: _objectSpread(_objectSpread({}, _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.panel), {}, {
        position: 'relative',
        marginTop: 3,
        paddingRight: 38,
        overflowWrap: 'anywhere',
        userSelect: 'text',
        fontSize: 'var(--curio-font-size-xs)',
        color: 'var(--curio-text-muted)',
        minHeight: 26
      })
    }, value || 'Unavailable', /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
      type: "button",
      "aria-label": "Copy ".concat(label.toLowerCase(), " source"),
      title: "Copy ".concat(label.toLowerCase(), " source"),
      disabled: !value || !((_navigator$clipboard2 = navigator.clipboard) !== null && _navigator$clipboard2 !== void 0 && _navigator$clipboard2.writeText),
      onClick: function onClick() {
        return copySource(label, value);
      },
      style: _objectSpread({
        position: 'absolute',
        top: 3,
        right: 3,
        width: 26,
        height: 26,
        padding: 0,
        display: 'grid',
        placeItems: 'center',
        cursor: 'pointer',
        border: '1px solid var(--curio-border)',
        borderRadius: 'var(--curio-radius-sm)',
        background: 'var(--curio-card-bg)',
        color: 'var(--curio-text-secondary)',
        fontSize: 'var(--curio-font-size-sm)',
        lineHeight: 1
      }, !value || !((_navigator$clipboard3 = navigator.clipboard) !== null && _navigator$clipboard3 !== void 0 && _navigator$clipboard3.writeText) ? {
        cursor: 'default',
        opacity: 0.5
      } : {})
    }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement(CurioUtilityIcon, {
      name: "copy"
    }))));
  }), copyStatus && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    role: "status",
    style: _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.status
  }, copyStatus)), _tileNeighbors__WEBPACK_IMPORTED_MODULE_14__.TILE_DIRECTIONS.map(function (direction) {
    var _neighborIndex$neighb2;
    var destination = neighborIndex === null || neighborIndex === void 0 || (_neighborIndex$neighb2 = neighborIndex.neighbors.get(tileId)) === null || _neighborIndex$neighb2 === void 0 ? void 0 : _neighborIndex$neighb2[direction];
    var disabled = !destination || !ready || !!navigationTarget || !onNavigate;
    var placement = direction === 'north' ? {
      top: 8,
      left: '50%',
      transform: 'translateX(-50%)'
    } : direction === 'south' ? {
      bottom: 8,
      left: '50%',
      transform: 'translateX(-50%)'
    } : direction === 'east' ? {
      right: 8,
      top: '50%',
      transform: 'translateY(-50%)'
    } : {
      left: 8,
      top: '50%',
      transform: 'translateY(-50%)'
    };
    return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
      key: direction,
      type: "button",
      "aria-label": "Navigate ".concat(direction),
      disabled: disabled,
      title: destination ? "Go ".concat(direction, " to tile ").concat(destination) : "No adjacent tile to the ".concat(direction),
      onPointerDown: function onPointerDown(event) {
        return event.stopPropagation();
      },
      onClick: function onClick(event) {
        event.stopPropagation();
        navigate(direction);
      },
      style: _objectSpread(_objectSpread({}, placement), {}, {
        position: 'absolute',
        zIndex: 5,
        width: 32,
        height: 32,
        padding: 0,
        border: '1px solid var(--curio-border-strong)',
        borderRadius: 'var(--curio-radius-md)',
        background: 'var(--curio-card-bg)',
        color: 'var(--curio-text-primary)',
        display: 'grid',
        placeItems: 'center',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.36 : 0.82,
        boxShadow: '0 1px 5px rgba(15,23,42,0.18)'
      })
    }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement(TileNavigationChevron, {
      direction: direction
    }));
  }), (loading || !!tileId && !imageReady && !error) && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    role: "status",
    style: _objectSpread(_objectSpread({}, _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.panel), {}, {
      position: 'absolute',
      zIndex: 2,
      margin: 8
    })
  }, "Loading tile\u2026"), error && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    role: "alert",
    style: _objectSpread(_objectSpread({}, _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.error), {}, {
      position: 'absolute',
      zIndex: 2,
      margin: 8
    })
  }, error), ready && !imageUrl && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    role: "status",
    style: _objectSpread(_objectSpread({}, _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.status), {}, {
      position: 'absolute',
      zIndex: 2,
      right: 8,
      bottom: 8
    })
  }, "Imagery unavailable for this tile. Network editing remains available."), !tileFeature && !loading && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: _objectSpread(_objectSpread({}, _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.status), {}, {
      padding: 12
    })
  }, "Connect an upstream Autark tile selection to review it."), ready && viewBounds && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("svg", {
    ref: imageSvg,
    "aria-label": "Sidewalk tile image and network",
    viewBox: "0 0 ".concat(VIEW, " ").concat(VIEW),
    preserveAspectRatio: "none",
    overflow: "hidden",
    style: {
      position: 'absolute',
      inset: 0,
      width: '100%',
      height: '100%',
      overflow: 'hidden',
      borderRadius: 'var(--curio-radius-md)',
      touchAction: 'none',
      cursor: mode === 'draw' || mode === 'delete-area' || mode === 'inspect' ? 'crosshair' : 'default'
    },
    onPointerDown: pointerDown,
    onPointerMove: pointerMove,
    onPointerUp: pointerUp,
    onPointerCancel: pointerCancel,
    onClick: onDrawClick,
    onDoubleClick: endDrawChain,
    onContextMenu: splitAt
  }, network.features.map(function (feature, i) {
    var _feature$id;
    return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("path", {
      key: "".concat((_feature$id = feature.id) !== null && _feature$id !== void 0 ? _feature$id : i),
      d: linePath(feature, viewBounds),
      fill: "none",
      stroke: NETWORK_STROKE,
      strokeWidth: NETWORK_STROKE_WIDTH,
      vectorEffect: "non-scaling-stroke",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    });
  }), endpoints.map(function (p, i) {
    var _pointToView3 = pointToView(p, viewBounds),
      _pointToView4 = _slicedToArray(_pointToView3, 2),
      cx = _pointToView4[0],
      cy = _pointToView4[1];
    var selected = selectedNode && coordinateKey(selectedNode) === coordinateKey(p);
    return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("ellipse", {
      key: i,
      "data-testid": "sidewalk-network-node",
      cx: cx,
      cy: cy,
      rx: NETWORK_NODE_RADIUS,
      ry: NETWORK_NODE_RADIUS * markerAspect,
      fill: selected ? '#ff0000' : NETWORK_STROKE,
      stroke: "#fff",
      strokeWidth: 2,
      onPointerDown: function onPointerDown(e) {
        return onNodePointerDown(e, p);
      }
    });
  }), drawingAnchor && !drawingAnchorIsNetworkNode && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("ellipse", {
    cx: pointToView(drawingAnchor, viewBounds)[0],
    cy: pointToView(drawingAnchor, viewBounds)[1],
    rx: NETWORK_NODE_RADIUS,
    ry: NETWORK_NODE_RADIUS * markerAspect,
    fill: NETWORK_STROKE,
    stroke: "#fff",
    strokeWidth: 2
  }), drawingAnchor && drawingCursor && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("line", {
    x1: pointToView(drawingAnchor, viewBounds)[0],
    y1: pointToView(drawingAnchor, viewBounds)[1],
    x2: pointToView(drawingCursor, viewBounds)[0],
    y2: pointToView(drawingCursor, viewBounds)[1],
    stroke: NETWORK_STROKE,
    strokeWidth: 2,
    strokeDasharray: "3 3",
    opacity: 0.85,
    vectorEffect: "non-scaling-stroke"
  }), pendingMarkerPoint && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("g", {
    "data-testid": "street-view-pending-marker",
    role: "img",
    "aria-label": "Requested location \u2014 Street View not loaded",
    pointerEvents: "none",
    transform: "translate(".concat(pendingMarkerPoint[0], " ").concat(pendingMarkerPoint[1], ")")
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("title", null, "Requested location \u2014 Street View not loaded"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("svg", {
    x: -STEWARDS_CAMERA_SIZE / 2,
    y: -STEWARDS_CAMERA_SIZE * markerAspect / 2,
    width: STEWARDS_CAMERA_SIZE,
    height: STEWARDS_CAMERA_SIZE * markerAspect,
    viewBox: "0 0 36 36",
    preserveAspectRatio: "none",
    overflow: "hidden"
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("path", {
    d: "M 4.48 14.38 A 14 14 0 0 1 31.52 14.38",
    fill: "none",
    stroke: "var(--curio-text-secondary)",
    strokeWidth: "7",
    strokeLinecap: "round",
    opacity: "0.82"
  }), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("circle", {
    cx: "18",
    cy: "18",
    r: "6",
    fill: "var(--curio-text-secondary)"
  }), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("circle", {
    cx: "18",
    cy: "18",
    r: "3.5",
    fill: "var(--curio-text-muted)",
    opacity: "0.5"
  }))), markerPoint && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("g", {
    "data-testid": "street-view-camera-marker",
    "aria-label": "Street View camera at its actual tile location",
    pointerEvents: "none",
    transform: "translate(".concat(markerPoint[0], " ").concat(markerPoint[1], ")")
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("svg", {
    x: -STEWARDS_CAMERA_SIZE / 2,
    y: -STEWARDS_CAMERA_SIZE * markerAspect / 2,
    width: STEWARDS_CAMERA_SIZE,
    height: STEWARDS_CAMERA_SIZE * markerAspect,
    viewBox: "0 0 36 36",
    preserveAspectRatio: "none",
    "data-testid": "stewards-camera-symbol",
    overflow: "visible",
    style: {
      filter: 'drop-shadow(0 2px 6px rgba(0,0,0,0.3))'
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("g", {
    "data-testid": "stewards-camera-heading",
    style: {
      transform: "rotate(".concat(displayHeading !== null && displayHeading !== void 0 ? displayHeading : 0, "deg)"),
      transformBox: 'view-box',
      transformOrigin: '50% 50%',
      transition: 'transform 0.1s ease'
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("path", {
    d: "M 4.48 14.38 A 14 14 0 0 1 31.52 14.38",
    fill: "none",
    stroke: "#ef4444",
    strokeWidth: "7",
    strokeLinecap: "round",
    opacity: "0.82"
  }), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("circle", {
    cx: "18",
    cy: "18",
    r: "6",
    fill: "#ef4444"
  }), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("circle", {
    cx: "18",
    cy: "18",
    r: "3.5",
    fill: "#dc2626",
    opacity: "0.5"
  })))), outside && outsideTagPoint && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("g", {
    "data-testid": "street-view-outside-cue",
    pointerEvents: "none",
    transform: "translate(".concat(outsideTagPoint[0], " ").concat(outsideTagPoint[1], ")")
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("svg", {
    "data-testid": "street-view-outside-tag",
    role: "status",
    x: outsideTagX,
    y: outsideTagY,
    width: OUTSIDE_CAMERA_TAG_WIDTH,
    height: OUTSIDE_CAMERA_TAG_HEIGHT * markerAspect,
    viewBox: "0 0 ".concat(OUTSIDE_CAMERA_TAG_WIDTH, " ").concat(OUTSIDE_CAMERA_TAG_HEIGHT),
    preserveAspectRatio: "none",
    overflow: "visible"
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("rect", {
    x: "1",
    y: "1",
    width: OUTSIDE_CAMERA_TAG_WIDTH - 2,
    height: OUTSIDE_CAMERA_TAG_HEIGHT - 2,
    rx: "10",
    fill: "#fff",
    stroke: "#ef4444",
    strokeWidth: "2"
  }), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("svg", {
    x: "15",
    y: "10",
    width: "32",
    height: "32",
    viewBox: "0 0 512 512",
    "data-testid": "street-view-outside-warning-icon",
    "aria-hidden": "true"
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("path", {
    fill: "#ef4444",
    d: "M256 0c14.7 0 28.2 8.1 35.2 21l216 400c6.7 12.4 6.4 27.4-.8 39.5S486.1 480 472 480L40 480c-14.1 0-27.2-7.4-34.4-19.5s-7.5-27.1-.8-39.5l216-400c7-12.9 20.5-21 35.2-21zm0 352a32 32 0 1 0 0 64 32 32 0 1 0 0-64zm0-192c-18.2 0-32.7 15.5-31.4 33.7l7.4 104c.9 12.5 11.4 22.3 23.9 22.3 12.6 0 23-9.7 23.9-22.3l7.4-104c1.3-18.2-13.1-33.7-31.4-33.7z"
  })), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("text", {
    x: "55",
    y: "34",
    fill: "#ef4444",
    fontSize: "25",
    fontWeight: "600",
    fontFamily: "var(--curio-font-family)"
  }, "Camera outside the active tile"))), marqueeStart && marqueeEnd && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("rect", {
    x: Math.min(marqueeStart[0], marqueeEnd[0]),
    y: Math.min(marqueeStart[1], marqueeEnd[1]),
    width: Math.abs(marqueeEnd[0] - marqueeStart[0]),
    height: Math.abs(marqueeEnd[1] - marqueeStart[1]),
    fill: "#e0000022",
    stroke: "#e00000",
    strokeDasharray: "6 4"
  }))), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: _objectSpread(_objectSpread(_objectSpread({}, _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.panel), _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.row), {}, {
      justifyContent: 'space-between',
      gap: 8
    })
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", null, ready ? "".concat(network.features.length, " lines") : 'No network loaded'), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", null, issues.length ? "".concat(issues.length, " blocking validation issue(s)") : ready ? network.features.length ? 'Geometry valid' : 'Empty network · geometry valid' : 'Validation unavailable')), navigationTarget && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    role: "status",
    style: _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.status
  }, "Loading tile ", navigationTarget, "\u2026"), movementNotice && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    role: "status",
    style: _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.warning
  }, movementNotice), outside && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    role: "status",
    style: _objectSpread(_objectSpread(_objectSpread({}, _curio_streetvision_1_sources_nodeUiStyles__WEBPACK_IMPORTED_MODULE_16__.nodeUiStyles.card), _curio_streetvision_1_sources_nodeUiStyles__WEBPACK_IMPORTED_MODULE_16__.nodeUiStyles.row), {}, {
      justifyContent: 'space-between'
    })
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", null, "Camera outside current tile \xB7 ", Math.round(outside.metres), " m from boundary"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    type: "button",
    onClick: openCameraTile,
    disabled: !cameraTileId || cameraTileId === tileId || !!navigationTarget || !currentInspection.current,
    style: _objectSpread(_objectSpread(_objectSpread({}, _curio_streetvision_1_sources_nodeUiStyles__WEBPACK_IMPORTED_MODULE_16__.nodeUiStyles.btn), _curio_streetvision_1_sources_nodeUiStyles__WEBPACK_IMPORTED_MODULE_16__.nodeUiStyles.btnSecondary), {}, {
      width: 'auto'
    })
  }, cameraTileId && cameraTileId !== tileId && currentInspection.current ? "Open camera tile ".concat(cameraTileId) : 'Camera tile unavailable')), requestedPoint && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    role: "status",
    style: _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.status
  }, "Requested Street View point: lon ", requestedPoint[0].toFixed(6), "\xB0, lat ", requestedPoint[1].toFixed(6), "\xB0"), requestedPoint && !camera && (inspectionStatus === null || inspectionStatus === void 0 ? void 0 : inspectionStatus.state) === 'missing-key' && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    role: "status",
    style: _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.panel
  }, "Street View requires an API key. Configure it in the connected Street View Panorama node."), requestedPoint && !camera && (inspectionStatus === null || inspectionStatus === void 0 ? void 0 : inspectionStatus.state) === 'invalid-key' && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    role: "alert",
    style: _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.warning
  }, "Street View needs a valid Maps JavaScript API key in the connected Panorama node."), requestedPoint && !camera && (inspectionStatus === null || inspectionStatus === void 0 ? void 0 : inspectionStatus.state) === 'loading' && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    role: "status",
    style: _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.panel
  }, "Loading Street View\u2026"), requestedPoint && !camera && ((inspectionStatus === null || inspectionStatus === void 0 ? void 0 : inspectionStatus.state) === 'error' || (inspectionStatus === null || inspectionStatus === void 0 ? void 0 : inspectionStatus.state) === 'unavailable') && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    role: "alert",
    style: _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.warning
  }, inspectionStatus.message || (inspectionStatus.state === 'unavailable' ? 'No nearby Street View panorama is available.' : 'Street View could not load. Check the browser key and connection, then Retry in Panorama.')), issues.length > 0 && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    role: "alert",
    style: _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.error
  }, issues.slice(0, 3).join(' ')), topologyWarnings.length > 0 && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("details", {
    "aria-label": "Sidewalk topology warnings",
    onToggle: function onToggle(event) {
      return setWarningsOpen(event.currentTarget.open);
    },
    style: _objectSpread(_objectSpread({}, _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.warning), {}, {
      maxHeight: warningsOpen ? 160 : 48
    })
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("summary", null, topologyWarnings.length, " topology warning(s)"), topologyWarnings.map(function (warning) {
    return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      key: warning.code,
      style: {
        marginTop: 5
      }
    }, warning.message, " Affected features: ", warning.featureIndexes.slice(0, 8).map(function (index) {
      var _network$features$ind, _network$features$ind2;
      return String((_network$features$ind = (_network$features$ind2 = network.features[index]) === null || _network$features$ind2 === void 0 ? void 0 : _network$features$ind2.id) !== null && _network$features$ind !== void 0 ? _network$features$ind : index + 1);
    }).join(', '), warning.featureIndexes.length > 8 ? " and ".concat(warning.featureIndexes.length - 8, " more") : '', ".");
  })), selectedNode && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_15__.sidewalkNodeStyles.helper
  }, "Node selected. Drag it onto another node to join the networks. Press Delete or Backspace to remove the node and its connected lines."));
}

/***/ },

/***/ "../../../packages/curio.sidewalk-stewards@1/sources/autkSelection.ts"
/*!****************************************************************************!*\
  !*** ../../../packages/curio.sidewalk-stewards@1/sources/autkSelection.ts ***!
  \****************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   featureForChannel: () => (/* binding */ featureForChannel),
/* harmony export */   featureIdForChannel: () => (/* binding */ featureIdForChannel),
/* harmony export */   featureIdsForChannel: () => (/* binding */ featureIdsForChannel),
/* harmony export */   featureIdsForSelection: () => (/* binding */ featureIdsForSelection),
/* harmony export */   featureIndicesForIds: () => (/* binding */ featureIndicesForIds),
/* harmony export */   latestAutkSelection: () => (/* binding */ latestAutkSelection),
/* harmony export */   selectionForChannel: () => (/* binding */ selectionForChannel)
/* harmony export */ });
function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
function _toConsumableArray(r) { return _arrayWithoutHoles(r) || _iterableToArray(r) || _unsupportedIterableToArray(r) || _nonIterableSpread(); }
function _nonIterableSpread() { throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _iterableToArray(r) { if ("undefined" != typeof Symbol && null != r[Symbol.iterator] || null != r["@@iterator"]) return Array.from(r); }
function _arrayWithoutHoles(r) { if (Array.isArray(r)) return _arrayLikeToArray(r); }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
/** Curio's interaction bus carries selections independently of a node's data output. */

/** The legacy row set remains available, while origin v1 identifies the one
 * map click (if any) independently of a multi-row plot brush. */
function latestAutkSelection(interactions) {
  var _detail$feature;
  if (!Array.isArray(interactions)) return null;
  var events = interactions.flatMap(function (interaction) {
    var _interaction$details, _ref, _detail$priority;
    var detail = interaction === null || interaction === void 0 || (_interaction$details = interaction.details) === null || _interaction$details === void 0 ? void 0 : _interaction$details.autk_selection;
    if (!detail || !Array.isArray(detail.data)) return [];
    return [{
      priority: Number((_ref = (_detail$priority = detail.priority) !== null && _detail$priority !== void 0 ? _detail$priority : interaction.priority) !== null && _ref !== void 0 ? _ref : 0),
      detail: detail
    }];
  });
  if (!events.length) return null;
  var priority = Math.max.apply(Math, _toConsumableArray(events.map(function (event) {
    return event.priority;
  })));
  var detail = events.filter(function (event) {
    return event.priority === priority;
  }).at(-1).detail;
  var indices = detail.data.filter(function (value) {
    return Number.isInteger(value) && Number(value) >= 0;
  });
  var origin = detail.selectionOrigin;
  var kind = (origin === null || origin === void 0 ? void 0 : origin.version) === 1 && (origin.kind === 'map-pick' || origin.kind === 'plot-brush') ? origin.kind : 'legacy';
  return {
    indices: indices,
    kind: kind,
    activeIndex: kind === 'map-pick' && Number.isInteger(origin.activeIndex) && origin.activeIndex >= 0 ? origin.activeIndex : null,
    candidateIndices: kind === 'plot-brush' ? indices : [],
    featureId: typeof detail.featureId === 'string' ? detail.featureId : null,
    feature: ((_detail$feature = detail.feature) === null || _detail$feature === void 0 ? void 0 : _detail$feature.type) === 'Feature' ? detail.feature : null,
    event: detail,
    layerRef: typeof detail.layerRef === 'string' ? detail.layerRef : null
  };
}
function stableFeatureId(feature) {
  var _ref2, _properties$tile_id;
  var properties = feature === null || feature === void 0 ? void 0 : feature.properties;
  var value = (_ref2 = (_properties$tile_id = properties === null || properties === void 0 ? void 0 : properties.tile_id) !== null && _properties$tile_id !== void 0 ? _properties$tile_id : properties === null || properties === void 0 ? void 0 : properties.tileId) !== null && _ref2 !== void 0 ? _ref2 : properties === null || properties === void 0 ? void 0 : properties.id;
  return typeof value === 'string' || typeof value === 'number' ? String(value) : null;
}

/** Stable IDs let linked selections survive different row ordering in map and plot inputs. */
function featureIdsForSelection(collection, indices) {
  if (!Array.isArray(collection === null || collection === void 0 ? void 0 : collection.features)) return [];
  return _toConsumableArray(new Set(indices.map(function (index) {
    return collection.features[index];
  }).map(stableFeatureId).filter(function (id) {
    return id !== null;
  })));
}

/** Resolve stable feature IDs to indices for the receiving Autark layer. */
function featureIndicesForIds(collection, ids) {
  if (!Array.isArray(collection === null || collection === void 0 ? void 0 : collection.features)) return [];
  var wanted = new Set(ids.map(String));
  var features = collection.features;
  return features.reduce(function (matches, feature, index) {
    var id = stableFeatureId(feature);
    if (id !== null && wanted.has(id)) matches.push(index);
    return matches;
  }, []);
}

/** Latest stable feature IDs for a channel, or null when it has not emitted IDs. */
function featureIdsForChannel(interactions, channel) {
  if (!Array.isArray(interactions)) return null;
  var matches = interactions.flatMap(function (interaction) {
    var _interaction$details2, _ref3, _detail$priority2;
    var detail = interaction === null || interaction === void 0 || (_interaction$details2 = interaction.details) === null || _interaction$details2 === void 0 ? void 0 : _interaction$details2.autk_selection;
    if ((detail === null || detail === void 0 ? void 0 : detail.channel) !== channel || !Array.isArray(detail.featureIds)) return [];
    return [{
      priority: Number((_ref3 = (_detail$priority2 = detail.priority) !== null && _detail$priority2 !== void 0 ? _detail$priority2 : interaction.priority) !== null && _ref3 !== void 0 ? _ref3 : 0),
      ids: detail.featureIds
    }];
  });
  if (matches.length === 0) return null;
  var priority = Math.max.apply(Math, _toConsumableArray(matches.map(function (item) {
    return item.priority;
  })));
  return _toConsumableArray(new Set(matches.filter(function (item) {
    return item.priority === priority;
  }).flatMap(function (item) {
    return item.ids.map(String);
  })));
}

/** Latest selected row indices for one channel, or null when that channel has no event. */
function selectionForChannel(interactions, channel) {
  if (!Array.isArray(interactions)) return null;
  var matches = interactions.flatMap(function (interaction) {
    var _interaction$details3, _ref4, _detail$priority3;
    var detail = interaction === null || interaction === void 0 || (_interaction$details3 = interaction.details) === null || _interaction$details3 === void 0 ? void 0 : _interaction$details3.autk_selection;
    if ((detail === null || detail === void 0 ? void 0 : detail.channel) !== channel) return [];
    var indices = Array.isArray(detail.data) ? detail.data.filter(function (index) {
      return Number.isInteger(index) && Number(index) >= 0;
    }) : [];
    return [{
      priority: Number((_ref4 = (_detail$priority3 = detail.priority) !== null && _detail$priority3 !== void 0 ? _detail$priority3 : interaction.priority) !== null && _ref4 !== void 0 ? _ref4 : 0),
      indices: indices
    }];
  });
  if (matches.length === 0) return null;
  var priority = Math.max.apply(Math, _toConsumableArray(matches.map(function (item) {
    return item.priority;
  })));
  return _toConsumableArray(new Set(matches.filter(function (item) {
    return item.priority === priority;
  }).flatMap(function (item) {
    return item.indices;
  })));
}
function featureIdForChannel(interactions, channel) {
  if (!Array.isArray(interactions)) return null;
  var matches = interactions.flatMap(function (interaction) {
    var _interaction$details4, _ref5, _detail$priority4;
    var detail = interaction === null || interaction === void 0 || (_interaction$details4 = interaction.details) === null || _interaction$details4 === void 0 ? void 0 : _interaction$details4.autk_selection;
    if ((detail === null || detail === void 0 ? void 0 : detail.channel) !== channel) return [];
    return [{
      priority: Number((_ref5 = (_detail$priority4 = detail.priority) !== null && _detail$priority4 !== void 0 ? _detail$priority4 : interaction.priority) !== null && _ref5 !== void 0 ? _ref5 : 0),
      id: detail.featureId
    }];
  });
  if (matches.length === 0) return null;
  var priority = Math.max.apply(Math, _toConsumableArray(matches.map(function (item) {
    return item.priority;
  })));
  var latest = matches.filter(function (item) {
    return item.priority === priority;
  }).at(-1);
  return typeof (latest === null || latest === void 0 ? void 0 : latest.id) === 'string' && latest.id ? latest.id : null;
}

/** The picked GeoJSON feature, carried with a map-pick so downstream tools do
 * not need to reconstruct a click from a possibly wrapped data artifact. */
function featureForChannel(interactions, channel) {
  var _matches$filter$at$fe, _matches$filter$at;
  if (!Array.isArray(interactions)) return null;
  var matches = interactions.flatMap(function (interaction) {
    var _interaction$details5, _ref6, _detail$priority5;
    var detail = interaction === null || interaction === void 0 || (_interaction$details5 = interaction.details) === null || _interaction$details5 === void 0 ? void 0 : _interaction$details5.autk_selection;
    if ((detail === null || detail === void 0 ? void 0 : detail.channel) !== channel || !detail.feature || _typeof(detail.feature) !== 'object') return [];
    return [{
      priority: Number((_ref6 = (_detail$priority5 = detail.priority) !== null && _detail$priority5 !== void 0 ? _detail$priority5 : interaction.priority) !== null && _ref6 !== void 0 ? _ref6 : 0),
      feature: detail.feature
    }];
  });
  if (matches.length === 0) return null;
  var priority = Math.max.apply(Math, _toConsumableArray(matches.map(function (item) {
    return item.priority;
  })));
  return (_matches$filter$at$fe = (_matches$filter$at = matches.filter(function (item) {
    return item.priority === priority;
  }).at(-1)) === null || _matches$filter$at === void 0 ? void 0 : _matches$filter$at.feature) !== null && _matches$filter$at$fe !== void 0 ? _matches$filter$at$fe : null;
}

/***/ },

/***/ "../../../packages/curio.sidewalk-stewards@1/sources/beforeAfterContext.ts"
/*!*********************************************************************************!*\
  !*** ../../../packages/curio.sidewalk-stewards@1/sources/beforeAfterContext.ts ***!
  \*********************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   CONTEXT_SCHEMA: () => (/* binding */ CONTEXT_SCHEMA),
/* harmony export */   contextConfig: () => (/* binding */ contextConfig),
/* harmony export */   contextOutput: () => (/* binding */ contextOutput),
/* harmony export */   hydrate: () => (/* binding */ hydrate),
/* harmony export */   prepareContext: () => (/* binding */ prepareContext),
/* harmony export */   readPreparedContext: () => (/* binding */ readPreparedContext),
/* harmony export */   sha256: () => (/* binding */ sha256),
/* harmony export */   withTileMeasurements: () => (/* binding */ withTileMeasurements)
/* harmony export */ });
/* harmony import */ var _resourceResolver__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! ./resourceResolver */ "../../../packages/curio.sidewalk-stewards@1/sources/resourceResolver.ts");
/* harmony import */ var _overviewData__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! ./overviewData */ "../../../packages/curio.sidewalk-stewards@1/sources/overviewData.ts");
function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
function _slicedToArray(r, e) { return _arrayWithHoles(r) || _iterableToArrayLimit(r, e) || _unsupportedIterableToArray(r, e) || _nonIterableRest(); }
function _nonIterableRest() { throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _iterableToArrayLimit(r, l) { var t = null == r ? null : "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (null != t) { var e, n, i, u, a = [], f = !0, o = !1; try { if (i = (t = t.call(r)).next, 0 === l) { if (Object(t) !== t) return; f = !1; } else for (; !(f = (e = i.call(t)).done) && (a.push(e.value), a.length !== l); f = !0); } catch (r) { o = !0, n = r; } finally { try { if (!f && null != t["return"] && (u = t["return"](), Object(u) !== u)) return; } finally { if (o) throw n; } } return a; } }
function _arrayWithHoles(r) { if (Array.isArray(r)) return r; }
function _toConsumableArray(r) { return _arrayWithoutHoles(r) || _iterableToArray(r) || _unsupportedIterableToArray(r) || _nonIterableSpread(); }
function _nonIterableSpread() { throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _iterableToArray(r) { if ("undefined" != typeof Symbol && null != r[Symbol.iterator] || null != r["@@iterator"]) return Array.from(r); }
function _arrayWithoutHoles(r) { if (Array.isArray(r)) return _arrayLikeToArray(r); }
function _createForOfIteratorHelper(r, e) { var t = "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (!t) { if (Array.isArray(r) || (t = _unsupportedIterableToArray(r)) || e && r && "number" == typeof r.length) { t && (r = t); var _n = 0, F = function F() {}; return { s: F, n: function n() { return _n >= r.length ? { done: !0 } : { done: !1, value: r[_n++] }; }, e: function e(r) { throw r; }, f: F }; } throw new TypeError("Invalid attempt to iterate non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); } var o, a = !0, u = !1; return { s: function s() { t = t.call(r); }, n: function n() { var r = t.next(); return a = r.done, r; }, e: function e(r) { u = !0, o = r; }, f: function f() { try { a || null == t["return"] || t["return"](); } finally { if (u) throw o; } } }; }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: !0, configurable: !0, writable: !0 }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == _typeof(i) ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != _typeof(t) || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r || "default"); if ("object" != _typeof(i)) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
function _regenerator() { /*! regenerator-runtime -- Copyright (c) 2014-present, Facebook, Inc. -- license (MIT): https://github.com/babel/babel/blob/main/packages/babel-helpers/LICENSE */ var e, t, r = "function" == typeof Symbol ? Symbol : {}, n = r.iterator || "@@iterator", o = r.toStringTag || "@@toStringTag"; function i(r, n, o, i) { var c = n && n.prototype instanceof Generator ? n : Generator, u = Object.create(c.prototype); return _regeneratorDefine2(u, "_invoke", function (r, n, o) { var i, c, u, f = 0, p = o || [], y = !1, G = { p: 0, n: 0, v: e, a: d, f: d.bind(e, 4), d: function d(t, r) { return i = t, c = 0, u = e, G.n = r, a; } }; function d(r, n) { for (c = r, u = n, t = 0; !y && f && !o && t < p.length; t++) { var o, i = p[t], d = G.p, l = i[2]; r > 3 ? (o = l === n) && (u = i[(c = i[4]) ? 5 : (c = 3, 3)], i[4] = i[5] = e) : i[0] <= d && ((o = r < 2 && d < i[1]) ? (c = 0, G.v = n, G.n = i[1]) : d < l && (o = r < 3 || i[0] > n || n > l) && (i[4] = r, i[5] = n, G.n = l, c = 0)); } if (o || r > 1) return a; throw y = !0, n; } return function (o, p, l) { if (f > 1) throw TypeError("Generator is already running"); for (y && 1 === p && d(p, l), c = p, u = l; (t = c < 2 ? e : u) || !y;) { i || (c ? c < 3 ? (c > 1 && (G.n = -1), d(c, u)) : G.n = u : G.v = u); try { if (f = 2, i) { if (c || (o = "next"), t = i[o]) { if (!(t = t.call(i, u))) throw TypeError("iterator result is not an object"); if (!t.done) return t; u = t.value, c < 2 && (c = 0); } else 1 === c && (t = i["return"]) && t.call(i), c < 2 && (u = TypeError("The iterator does not provide a '" + o + "' method"), c = 1); i = e; } else if ((t = (y = G.n < 0) ? u : r.call(n, G)) !== a) break; } catch (t) { i = e, c = 1, u = t; } finally { f = 1; } } return { value: t, done: y }; }; }(r, o, i), !0), u; } var a = {}; function Generator() {} function GeneratorFunction() {} function GeneratorFunctionPrototype() {} t = Object.getPrototypeOf; var c = [][n] ? t(t([][n]())) : (_regeneratorDefine2(t = {}, n, function () { return this; }), t), u = GeneratorFunctionPrototype.prototype = Generator.prototype = Object.create(c); function f(e) { return Object.setPrototypeOf ? Object.setPrototypeOf(e, GeneratorFunctionPrototype) : (e.__proto__ = GeneratorFunctionPrototype, _regeneratorDefine2(e, o, "GeneratorFunction")), e.prototype = Object.create(u), e; } return GeneratorFunction.prototype = GeneratorFunctionPrototype, _regeneratorDefine2(u, "constructor", GeneratorFunctionPrototype), _regeneratorDefine2(GeneratorFunctionPrototype, "constructor", GeneratorFunction), GeneratorFunction.displayName = "GeneratorFunction", _regeneratorDefine2(GeneratorFunctionPrototype, o, "GeneratorFunction"), _regeneratorDefine2(u), _regeneratorDefine2(u, o, "Generator"), _regeneratorDefine2(u, n, function () { return this; }), _regeneratorDefine2(u, "toString", function () { return "[object Generator]"; }), (_regenerator = function _regenerator() { return { w: i, m: f }; })(); }
function _regeneratorDefine2(e, r, n, t) { var i = Object.defineProperty; try { i({}, "", {}); } catch (e) { i = 0; } _regeneratorDefine2 = function _regeneratorDefine(e, r, n, t) { function o(r, n) { _regeneratorDefine2(e, r, function (e) { return this._invoke(r, n, e); }); } r ? i ? i(e, r, { value: n, enumerable: !t, configurable: !t, writable: !t }) : e[r] = n : (o("next", 0), o("throw", 1), o("return", 2)); }, _regeneratorDefine2(e, r, n, t); }
function asyncGeneratorStep(n, t, e, r, o, a, c) { try { var i = n[a](c), u = i.value; } catch (n) { return void e(n); } i.done ? t(u) : Promise.resolve(u).then(r, o); }
function _asyncToGenerator(n) { return function () { var t = this, e = arguments; return new Promise(function (r, o) { var a = n.apply(t, e); function _next(n) { asyncGeneratorStep(a, r, o, _next, _throw, "next", n); } function _throw(n) { asyncGeneratorStep(a, r, o, _next, _throw, "throw", n); } _next(void 0); }); }; }


var CONTEXT_SCHEMA = 'io.github.lzml0.sidewalk-stewards/context/v1';
var collection = function collection(v) {
  return (v === null || v === void 0 ? void 0 : v.type) === 'FeatureCollection' && Array.isArray(v.features);
};
var hash = function hash(v) {
  return typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
};
function path(v) {
  return typeof v === 'string' && !!v && v === v.trim() && !/\s/.test(v) && !v.startsWith('//') && (!/^[a-z][a-z0-9+.-]*:/i.test(v) || /^https?:\/\//i.test(v));
}
function hydrate(_x, _x2) {
  return _hydrate.apply(this, arguments);
}
function _hydrate() {
  _hydrate = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee2(value, signal) {
    var _value$data;
    var _t, _t2, _t3, _t4, _t5, _t6, _t7, _t8, _t9, _t0, _t1, _t10;
    return _regenerator().w(function (_context2) {
      while (1) switch (_context2.p = _context2.n) {
        case 0:
          if (!(typeof value === 'string')) {
            _context2.n = 4;
            break;
          }
          if (value.trim()) {
            _context2.n = 1;
            break;
          }
          return _context2.a(2, null);
        case 1:
          _context2.p = 1;
          return _context2.a(2, hydrate(JSON.parse(value), signal));
        case 2:
          _context2.p = 2;
          _t = _context2.v;
          _t2 = hydrate;
          _context2.n = 3;
          return (0,_resourceResolver__WEBPACK_IMPORTED_MODULE_0__.fetchData)(value, signal);
        case 3:
          return _context2.a(2, _t2(_context2.v, signal));
        case 4:
          if (!(value !== null && value !== void 0 && value.path && !value.data)) {
            _context2.n = 6;
            break;
          }
          _t3 = hydrate;
          _t4 = _objectSpread;
          _t5 = _objectSpread({}, value);
          _t6 = {};
          _t7 = undefined;
          _context2.n = 5;
          return (0,_resourceResolver__WEBPACK_IMPORTED_MODULE_0__.fetchData)(value.path, signal);
        case 5:
          _t8 = _context2.v;
          return _context2.a(2, _t3(_t4(_t5, _t6, {
            path: _t7,
            data: _t8
          }), signal));
        case 6:
          if (!((value === null || value === void 0 ? void 0 : value.dataType) === 'dict')) {
            _context2.n = 7;
            break;
          }
          return _context2.a(2, hydrate(value.data, signal));
        case 7:
          if (!((value === null || value === void 0 ? void 0 : value.dataType) === 'outputs')) {
            _context2.n = 9;
            break;
          }
          _t9 = _objectSpread;
          _t0 = _objectSpread({}, value);
          _t1 = {};
          _context2.n = 8;
          return Promise.all(((_value$data = value.data) !== null && _value$data !== void 0 ? _value$data : []).map(function (v) {
            return hydrate(v, signal);
          }));
        case 8:
          _t10 = _context2.v;
          return _context2.a(2, _t9(_t0, _t1, {
            data: _t10
          }));
        case 9:
          return _context2.a(2, value);
      }
    }, _callee2, null, [[1, 2]]);
  }));
  return _hydrate.apply(this, arguments);
}
function sha256(_x3) {
  return _sha.apply(this, arguments);
}
/** Both real Data Loading dicts must be supplied through separate input circles. */
function _sha() {
  _sha = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee3(value) {
    var bytes, digest;
    return _regenerator().w(function (_context3) {
      while (1) switch (_context3.n) {
        case 0:
          bytes = new TextEncoder().encode(value);
          _context3.n = 1;
          return globalThis.crypto.subtle.digest('SHA-256', bytes);
        case 1:
          digest = _context3.v;
          return _context3.a(2, _toConsumableArray(new Uint8Array(digest)).map(function (v) {
            return v.toString(16).padStart(2, '0');
          }).join(''));
      }
    }, _callee3);
  }));
  return _sha.apply(this, arguments);
}
function prepareContext(_x4) {
  return _prepareContext.apply(this, arguments);
}
function _prepareContext() {
  _prepareContext = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee4(input) {
    var _image$georeferencing, _image$georeferencing2, _image$georeferencing3;
    var load,
      digest,
      signal,
      bundle,
      values,
      images,
      networks,
      image,
      original,
      source,
      _yield$Promise$all,
      _yield$Promise$all2,
      grid,
      boundaries,
      context,
      sourceIdentity,
      _args4 = arguments;
    return _regenerator().w(function (_context4) {
      while (1) switch (_context4.n) {
        case 0:
          load = _args4.length > 1 && _args4[1] !== undefined ? _args4[1] : (/*#__PURE__*/function () {
            var _ref = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee(url, signal) {
              var response;
              return _regenerator().w(function (_context) {
                while (1) switch (_context.n) {
                  case 0:
                    _context.n = 1;
                    return fetch((0,_resourceResolver__WEBPACK_IMPORTED_MODULE_0__.assetUrl)(url), {
                      signal: signal
                    });
                  case 1:
                    response = _context.v;
                    if (response.ok) {
                      _context.n = 2;
                      break;
                    }
                    throw new Error("Declared context resource failed (HTTP ".concat(response.status, "): ").concat(url));
                  case 2:
                    return _context.a(2, response.json());
                }
              }, _callee);
            }));
            return function (_x5, _x6) {
              return _ref.apply(this, arguments);
            };
          }());
          digest = _args4.length > 2 && _args4[2] !== undefined ? _args4[2] : sha256;
          signal = _args4.length > 3 ? _args4[3] : undefined;
          _context4.n = 1;
          return hydrate(input, signal);
        case 1:
          bundle = _context4.v;
          values = (bundle === null || bundle === void 0 ? void 0 : bundle.dataType) === 'outputs' && Array.isArray(bundle.data) ? bundle.data : [];
          images = values.filter(function (v) {
            return (v === null || v === void 0 ? void 0 : v.kind) === 'sidewalk-image';
          });
          networks = values.filter(function (v) {
            return (v === null || v === void 0 ? void 0 : v.kind) === 'sidewalk-network';
          });
          if (!(images.length !== 1 || networks.length !== 1 || values.length !== 2)) {
            _context4.n = 2;
            break;
          }
          throw new Error('Required inputs: one satellite reference and one original network in separate Sidewalk Prepare input circles.');
        case 2:
          image = images[0], original = networks[0];
          source = image.source;
          if (!(!image.datasetId || image.datasetId !== original.datasetId || !hash(image.sha256) || !hash(original.sha256) || !hash((_image$georeferencing = image.georeferencing) === null || _image$georeferencing === void 0 ? void 0 : _image$georeferencing.gridSha256) || !((_image$georeferencing2 = image.georeferencing) !== null && _image$georeferencing2 !== void 0 && _image$georeferencing2.mapping) || !image.georeferencing.crs || ((_image$georeferencing3 = image.georeferencing.bounds) === null || _image$georeferencing3 === void 0 ? void 0 : _image$georeferencing3.length) !== 4 || !image.georeferencing.bounds.every(Number.isFinite) || (source === null || source === void 0 ? void 0 : source.type) !== 'geotiff' || !path(source.geotiffFileUrl) || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(source.outputTableName) || ['upstream', 'sidewalk_network', 'tile_boundaries'].includes(source.outputTableName) || !/^EPSG:[1-9]\d*$/.test(source.coordinateFormat) || source.coordinateFormat !== image.georeferencing.crs || !path(image.gridUrl) || !path(image.boundariesUrl) || !path(image.imageUrlTemplate) || !image.imageUrlTemplate.includes('{tile_id}') || !path(original.url) || original.crs !== 'EPSG:4326' || !collection(original.data))) {
            _context4.n = 3;
            break;
          }
          throw new Error('Invalid or mismatched satellite/network source identity, GeoTIFF reference, CRS or declared resources.');
        case 3:
          _context4.n = 4;
          return Promise.all([load(image.gridUrl, signal), load(image.boundariesUrl, signal)]);
        case 4:
          _yield$Promise$all = _context4.v;
          _yield$Promise$all2 = _slicedToArray(_yield$Promise$all, 2);
          grid = _yield$Promise$all2[0];
          boundaries = _yield$Promise$all2[1];
          if (!(!collection(grid) || !collection(boundaries))) {
            _context4.n = 5;
            break;
          }
          throw new Error('Declared grid and boundaries must be GeoJSON FeatureCollections.');
        case 5:
          context = {
            grid: _objectSpread(_objectSpread({}, grid), {}, {
              features: grid.features.map(function (f) {
                var _f$properties$tile_id, _f$properties;
                return _objectSpread(_objectSpread({}, f), {}, {
                  properties: _objectSpread(_objectSpread({}, f.properties), {}, {
                    image_url: image.imageUrlTemplate.replace('{tile_id}', String((_f$properties$tile_id = (_f$properties = f.properties) === null || _f$properties === void 0 ? void 0 : _f$properties.tile_id) !== null && _f$properties$tile_id !== void 0 ? _f$properties$tile_id : ''))
                  })
                });
              })
            }),
            network: original.data,
            boundaries: boundaries
          };
          (0,_overviewData__WEBPACK_IMPORTED_MODULE_1__.validateOverview)(context);
          _context4.n = 6;
          return digest((0,_overviewData__WEBPACK_IMPORTED_MODULE_1__.stableJson)([image, original, grid, boundaries]));
        case 6:
          sourceIdentity = _context4.v;
          return _context4.a(2, _objectSpread(_objectSpread({}, context), {}, {
            schema: CONTEXT_SCHEMA,
            image: image,
            original: {
              kind: original.kind,
              datasetId: original.datasetId,
              url: original.url,
              sha256: original.sha256,
              crs: original.crs
            },
            sourceIdentity: sourceIdentity
          }));
      }
    }, _callee4);
  }));
  return _prepareContext.apply(this, arguments);
}
function contextConfig(context, persisted) {
  return _objectSpread(_objectSpread({}, persisted), {}, {
    mode: 'input-overview',
    imageUrlTemplate: context.image.imageUrlTemplate,
    networkUrlTemplate: context.original.url,
    overview: {
      datasetId: context.image.datasetId,
      gridUrl: context.image.gridUrl,
      boundariesUrl: context.image.boundariesUrl,
      networkUrl: context.original.url,
      sourceIdentity: context.sourceIdentity
    }
  });
}
/** Keep sparse measured rows separate from the complete editing and map grid. */
function withTileMeasurements(context, measurements, fields) {
  if (!collection(measurements) || !fields.length || !fields.every(function (field) {
    return typeof field === 'string' && !!field.trim() && field !== 'tile_id';
  })) {
    throw new Error('Tile measurements require a GeoJSON FeatureCollection and named metric fields.');
  }
  var byId = new Map();
  var gridIds = new Set(context.grid.features.map(function (feature) {
    var _feature$properties;
    return String((_feature$properties = feature.properties) === null || _feature$properties === void 0 ? void 0 : _feature$properties.tile_id);
  }));
  var _iterator = _createForOfIteratorHelper(measurements.features),
    _step;
  try {
    for (_iterator.s(); !(_step = _iterator.n()).done;) {
      var _feature$properties4;
      var feature = _step.value;
      var id = (_feature$properties4 = feature.properties) === null || _feature$properties4 === void 0 ? void 0 : _feature$properties4.tile_id;
      if (id === undefined || id === null || !gridIds.has(String(id)) || byId.has(String(id))) {
        throw new Error("Tile measurement has a missing, duplicate, or unknown tile ID: ".concat(String(id)));
      }
      var values = {};
      var _iterator2 = _createForOfIteratorHelper(fields),
        _step2;
      try {
        for (_iterator2.s(); !(_step2 = _iterator2.n()).done;) {
          var _feature$properties5;
          var field = _step2.value;
          var value = (_feature$properties5 = feature.properties) === null || _feature$properties5 === void 0 ? void 0 : _feature$properties5[field];
          if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error("Invalid measured ".concat(field, " for tile ").concat(String(id)));
          values[field] = value;
        }
      } catch (err) {
        _iterator2.e(err);
      } finally {
        _iterator2.f();
      }
      byId.set(String(id), values);
    }
  } catch (err) {
    _iterator.e(err);
  } finally {
    _iterator.f();
  }
  return _objectSpread(_objectSpread({}, context), {}, {
    measurements: _objectSpread(_objectSpread({}, measurements), {}, {
      features: measurements.features.map(function (feature) {
        var _feature$properties2, _feature$properties3;
        return _objectSpread(_objectSpread({}, feature), {}, {
          properties: _objectSpread({
            tile_id: (_feature$properties2 = feature.properties) === null || _feature$properties2 === void 0 ? void 0 : _feature$properties2.tile_id
          }, byId.get(String((_feature$properties3 = feature.properties) === null || _feature$properties3 === void 0 ? void 0 : _feature$properties3.tile_id)))
        });
      })
    })
  });
}
function contextOutput(context, config, latest) {
  var output = (0,_overviewData__WEBPACK_IMPORTED_MODULE_1__.buildOverview)(context, contextConfig(context, config), latest);
  return _objectSpread(_objectSpread({}, output), {}, {
    data: [].concat(_toConsumableArray(output.data), [{
      dataType: 'dict',
      data: _objectSpread({}, context.image.source)
    }], _toConsumableArray(context.measurements ? [{
      dataType: 'geodataframe',
      layerName: 'sidewalk_typology',
      layerType: 'polygons',
      data: context.measurements
    }] : [])),
    metadata: _objectSpread(_objectSpread({}, output.metadata), {}, {
      sidewalkContext: {
        schema: CONTEXT_SCHEMA,
        image: context.image,
        original: context.original,
        sourceIdentity: context.sourceIdentity
      }
    })
  });
}
/** Reads only the explicit preparation output; legacy fixed fixtures are never a fallback. */
function readPreparedContext(_x7, _x8) {
  return _readPreparedContext.apply(this, arguments);
}
function _readPreparedContext() {
  _readPreparedContext = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee5(input, signal) {
    var _value$metadata, _layers$find, _layers$find2, _layers$find3, _layers$find4;
    var value, metadata, layers, grid, network, boundaries, measurements, context;
    return _regenerator().w(function (_context5) {
      while (1) switch (_context5.n) {
        case 0:
          _context5.n = 1;
          return hydrate(input, signal);
        case 1:
          value = _context5.v;
          metadata = value === null || value === void 0 || (_value$metadata = value.metadata) === null || _value$metadata === void 0 ? void 0 : _value$metadata.sidewalkContext;
          layers = (value === null || value === void 0 ? void 0 : value.dataType) === 'outputs' && Array.isArray(value.data) ? value.data : [];
          grid = (_layers$find = layers.find(function (v) {
            return (v === null || v === void 0 ? void 0 : v.layerName) === 'upstream';
          })) === null || _layers$find === void 0 ? void 0 : _layers$find.data;
          network = (_layers$find2 = layers.find(function (v) {
            return (v === null || v === void 0 ? void 0 : v.layerName) === 'sidewalk_network';
          })) === null || _layers$find2 === void 0 ? void 0 : _layers$find2.data;
          boundaries = (_layers$find3 = layers.find(function (v) {
            return (v === null || v === void 0 ? void 0 : v.layerName) === 'tile_boundaries';
          })) === null || _layers$find3 === void 0 ? void 0 : _layers$find3.data;
          measurements = (_layers$find4 = layers.find(function (v) {
            return (v === null || v === void 0 ? void 0 : v.layerName) === 'sidewalk_typology';
          })) === null || _layers$find4 === void 0 ? void 0 : _layers$find4.data;
          if (!((metadata === null || metadata === void 0 ? void 0 : metadata.schema) !== CONTEXT_SCHEMA || !hash(metadata.sourceIdentity) || !collection(grid) || !collection(network) || !collection(boundaries))) {
            _context5.n = 2;
            break;
          }
          throw new Error('Prepared satellite and original-network inputs are required. Connect Sidewalk Prepare; no fixture fallback is used.');
        case 2:
          if (!(measurements !== undefined && !collection(measurements))) {
            _context5.n = 3;
            break;
          }
          throw new Error('Invalid prepared measured tile layer.');
        case 3:
          context = _objectSpread(_objectSpread({}, metadata), {}, {
            grid: grid,
            network: network,
            boundaries: boundaries
          }, measurements ? {
            measurements: measurements
          } : {});
          (0,_overviewData__WEBPACK_IMPORTED_MODULE_1__.validateOverview)(context);
          return _context5.a(2, context);
      }
    }, _callee5);
  }));
  return _readPreparedContext.apply(this, arguments);
}

/***/ },

/***/ "../../../packages/curio.sidewalk-stewards@1/sources/cameraBoundary.ts"
/*!*****************************************************************************!*\
  !*** ../../../packages/curio.sidewalk-stewards@1/sources/cameraBoundary.ts ***!
  \*****************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   cameraBoundary: () => (/* binding */ cameraBoundary)
/* harmony export */ });
/* harmony import */ var _streetViewImages__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! ./streetViewImages */ "../../../packages/curio.sidewalk-stewards@1/sources/streetViewImages.ts");
function _createForOfIteratorHelper(r, e) { var t = "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (!t) { if (Array.isArray(r) || (t = _unsupportedIterableToArray(r)) || e && r && "number" == typeof r.length) { t && (r = t); var _n = 0, F = function F() {}; return { s: F, n: function n() { return _n >= r.length ? { done: !0 } : { done: !1, value: r[_n++] }; }, e: function e(r) { throw r; }, f: F }; } throw new TypeError("Invalid attempt to iterate non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); } var o, a = !0, u = !1; return { s: function s() { t = t.call(r); }, n: function n() { var r = t.next(); return a = r.done, r; }, e: function e(r) { u = !0, o = r; }, f: function f() { try { a || null == t["return"] || t["return"](); } finally { if (u) throw o; } } }; }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }


/** Nearest geographic boundary point and true distance for an off-tile camera. */
function cameraBoundary(point, polygon) {
  if ((0,_streetViewImages__WEBPACK_IMPORTED_MODULE_0__.pointInPolygon)(point, polygon)) return null;
  var latitude = point[1] * Math.PI / 180;
  var xScale = 111320 * Math.max(0.01, Math.cos(latitude));
  var yScale = 111320;
  var best = null;
  var bestDistance = Infinity;
  var _iterator = _createForOfIteratorHelper(polygon.coordinates),
    _step;
  try {
    for (_iterator.s(); !(_step = _iterator.n()).done;) {
      var ring = _step.value;
      for (var index = 0; index < ring.length; index += 1) {
        var a = ring[index];
        var b = ring[(index + 1) % ring.length];
        var dx = (b[0] - a[0]) * xScale;
        var dy = (b[1] - a[1]) * yScale;
        var px = (point[0] - a[0]) * xScale;
        var py = (point[1] - a[1]) * yScale;
        var factor = Math.max(0, Math.min(1, (px * dx + py * dy) / (dx * dx + dy * dy || 1)));
        var candidate = [a[0] + (b[0] - a[0]) * factor, a[1] + (b[1] - a[1]) * factor];
        var metres = (0,_streetViewImages__WEBPACK_IMPORTED_MODULE_0__.distanceMeters)(point, candidate);
        if (metres < bestDistance) {
          best = candidate;
          bestDistance = metres;
        }
      }
    }
  } catch (err) {
    _iterator.e(err);
  } finally {
    _iterator.f();
  }
  return best ? {
    nearest: best,
    metres: bestDistance
  } : null;
}

/***/ },

/***/ "../../../packages/curio.sidewalk-stewards@1/sources/networkEditContract.ts"
/*!**********************************************************************************!*\
  !*** ../../../packages/curio.sidewalk-stewards@1/sources/networkEditContract.ts ***!
  \**********************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   SIDEWALK_NETWORK_EDIT_CHANNEL: () => (/* binding */ SIDEWALK_NETWORK_EDIT_CHANNEL),
/* harmony export */   SIDEWALK_NETWORK_EDIT_SCHEMA: () => (/* binding */ SIDEWALK_NETWORK_EDIT_SCHEMA),
/* harmony export */   isSidewalkNetworkEdit: () => (/* binding */ isSidewalkNetworkEdit),
/* harmony export */   makeNetworkEditEnvelope: () => (/* binding */ makeNetworkEditEnvelope)
/* harmony export */ });
function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: !0, configurable: !0, writable: !0 }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == _typeof(i) ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != _typeof(t) || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r || "default"); if ("object" != _typeof(i)) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
/** Versioned package-owned interaction payload sent only across interaction edges. */
var SIDEWALK_NETWORK_EDIT_CHANNEL = 'sidewalk.network-edit';
var SIDEWALK_NETWORK_EDIT_SCHEMA = 'io.github.lzml0.sidewalk-stewards/network-edit';
function makeNetworkEditEnvelope(edit) {
  return _objectSpread({
    schema: SIDEWALK_NETWORK_EDIT_SCHEMA,
    version: 1
  }, edit);
}
function isSidewalkNetworkEdit(value) {
  var _edit$after;
  var edit = value;
  return !!edit && edit.schema === SIDEWALK_NETWORK_EDIT_SCHEMA && edit.version === 1 && typeof edit.tileId === 'string' && Number.isInteger(edit.editRevision) && ((_edit$after = edit.after) === null || _edit$after === void 0 ? void 0 : _edit$after.type) === 'FeatureCollection' && Array.isArray(edit.after.features);
}

/***/ },

/***/ "../../../packages/curio.sidewalk-stewards@1/sources/overviewData.ts"
/*!***************************************************************************!*\
  !*** ../../../packages/curio.sidewalk-stewards@1/sources/overviewData.ts ***!
  \***************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   buildOverview: () => (/* binding */ buildOverview),
/* harmony export */   committedSignature: () => (/* binding */ committedSignature),
/* harmony export */   overviewIdentity: () => (/* binding */ overviewIdentity),
/* harmony export */   savedTile: () => (/* binding */ savedTile),
/* harmony export */   scopeLegacyTiles: () => (/* binding */ scopeLegacyTiles),
/* harmony export */   stableJson: () => (/* binding */ stableJson),
/* harmony export */   tileStorageKey: () => (/* binding */ tileStorageKey),
/* harmony export */   validateOverview: () => (/* binding */ validateOverview)
/* harmony export */ });
/* harmony import */ var _sidewalkEditOperations__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! ./sidewalkEditOperations */ "../../../packages/curio.sidewalk-stewards@1/sources/sidewalkEditOperations.ts");
var _excluded = ["interacted"];
function _objectWithoutProperties(e, t) { if (null == e) return {}; var o, r, i = _objectWithoutPropertiesLoose(e, t); if (Object.getOwnPropertySymbols) { var n = Object.getOwnPropertySymbols(e); for (r = 0; r < n.length; r++) o = n[r], -1 === t.indexOf(o) && {}.propertyIsEnumerable.call(e, o) && (i[o] = e[o]); } return i; }
function _objectWithoutPropertiesLoose(r, e) { if (null == r) return {}; var t = {}; for (var n in r) if ({}.hasOwnProperty.call(r, n)) { if (-1 !== e.indexOf(n)) continue; t[n] = r[n]; } return t; }
function _toConsumableArray(r) { return _arrayWithoutHoles(r) || _iterableToArray(r) || _unsupportedIterableToArray(r) || _nonIterableSpread(); }
function _nonIterableSpread() { throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _iterableToArray(r) { if ("undefined" != typeof Symbol && null != r[Symbol.iterator] || null != r["@@iterator"]) return Array.from(r); }
function _arrayWithoutHoles(r) { if (Array.isArray(r)) return _arrayLikeToArray(r); }
function _createForOfIteratorHelper(r, e) { var t = "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (!t) { if (Array.isArray(r) || (t = _unsupportedIterableToArray(r)) || e && r && "number" == typeof r.length) { t && (r = t); var _n = 0, F = function F() {}; return { s: F, n: function n() { return _n >= r.length ? { done: !0 } : { done: !1, value: r[_n++] }; }, e: function e(r) { throw r; }, f: F }; } throw new TypeError("Invalid attempt to iterate non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); } var o, a = !0, u = !1; return { s: function s() { t = t.call(r); }, n: function n() { var r = t.next(); return a = r.done, r; }, e: function e(r) { u = !0, o = r; }, f: function f() { try { a || null == t["return"] || t["return"](); } finally { if (u) throw o; } } }; }
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

function stableJson(value) {
  return JSON.stringify(value, function (_key, item) {
    return item && _typeof(item) === 'object' && !Array.isArray(item) ? Object.fromEntries(Object.keys(item).sort().map(function (key) {
      return [key, item[key]];
    })) : item;
  });
}
function overviewIdentity(config) {
  return stableJson([config.overview, config.imageUrlTemplate, config.networkUrlTemplate]);
}
function tileStorageKey(config, tileId) {
  return config.overview ? "".concat(overviewIdentity(config), ":").concat(tileId) : tileId;
}
function legacyDataset(config) {
  var o = config.overview;
  var root = 'docs/examples/data/sidewalk-stewards-regions';
  return !!o && !o.sourceIdentity && o.datasetId === 'recife-z19' && o.gridUrl === "".concat(root, "/tile-grid.geojson") && o.networkUrl === "".concat(root, "/overview-network.geojson") && o.boundariesUrl === "".concat(root, "/tile-boundaries.geojson") && config.imageUrlTemplate === "".concat(root, "/tiles/{tile_id}.png") && config.networkUrlTemplate === "".concat(root, "/tile-network/{tile_id}.geojson");
}
function savedTile(config, tileId) {
  var current = config.byTile[tileStorageKey(config, tileId)];
  if (current) return current;
  // Untagged v1 records belong only to the original prepared Recife dataset.
  return !config.overview || legacyDataset(config) ? config.byTile[tileId] : undefined;
}
/** Move original unscoped Recife records into the same dataset-keyed store on persistence. */
function scopeLegacyTiles(config) {
  if (!legacyDataset(config)) return config;
  var byTile = _objectSpread({}, config.byTile);
  for (var _i = 0, _Object$entries = Object.entries(config.byTile); _i < _Object$entries.length; _i++) {
    var _byTile$key;
    var _Object$entries$_i = _slicedToArray(_Object$entries[_i], 2),
      id = _Object$entries$_i[0],
      record = _Object$entries$_i[1];
    if (!/^[a-zA-Z0-9_-]+$/.test(id)) continue;
    var key = tileStorageKey(config, id);
    (_byTile$key = byTile[key]) !== null && _byTile$key !== void 0 ? _byTile$key : byTile[key] = record;
    delete byTile[id];
  }
  return _objectSpread(_objectSpread({}, config), {}, {
    byTile: byTile
  });
}
function committedSignature(config, grid) {
  return stableJson(grid.features.map(function (feature) {
    var _feature$properties$t, _feature$properties;
    var id = String((_feature$properties$t = (_feature$properties = feature.properties) === null || _feature$properties === void 0 ? void 0 : _feature$properties.tile_id) !== null && _feature$properties$t !== void 0 ? _feature$properties$t : '');
    var record = savedTile(config, id);
    return [id, record === null || record === void 0 ? void 0 : record.committedNetwork, record === null || record === void 0 ? void 0 : record.revision, record === null || record === void 0 ? void 0 : record.provenance, record === null || record === void 0 ? void 0 : record.committedEdit];
  }));
}
function validateOverview(context) {
  var ids = new Set();
  if (!context.grid.features.length) throw new Error('Overview grid contains no tiles.');
  var _iterator = _createForOfIteratorHelper(context.grid.features),
    _step;
  try {
    var _loop = function _loop() {
      var _tile$properties, _tile$geometry;
      var tile = _step.value;
      var id = (_tile$properties = tile.properties) === null || _tile$properties === void 0 ? void 0 : _tile$properties.tile_id;
      var bounds = (0,_sidewalkEditOperations__WEBPACK_IMPORTED_MODULE_0__.featureBounds)(tile);
      if (typeof id !== 'string' || !id || ids.has(id)) throw new Error('Overview tiles need unique tile_id values.');
      if (((_tile$geometry = tile.geometry) === null || _tile$geometry === void 0 ? void 0 : _tile$geometry.type) !== 'Polygon' || !bounds || bounds.some(function (v) {
        return !Number.isFinite(v);
      }) || bounds[0] >= bounds[2] || bounds[1] >= bounds[3] || tile.geometry.coordinates.length !== 1 || tile.geometry.coordinates[0].length !== 5 || tile.geometry.coordinates[0].some(function (p) {
        return ![bounds[0], bounds[2]].includes(p[0]) || ![bounds[1], bounds[3]].includes(p[1]);
      })) {
        throw new Error('Overview replacement requires rectangular tile polygons.');
      }
      ids.add(id);
    };
    for (_iterator.s(); !(_step = _iterator.n()).done;) {
      _loop();
    }
  } catch (err) {
    _iterator.e(err);
  } finally {
    _iterator.f();
  }
  if (context.network.features.some(function (f) {
    var _f$geometry$type, _f$geometry;
    return !['LineString', 'MultiLineString'].includes((_f$geometry$type = (_f$geometry = f.geometry) === null || _f$geometry === void 0 ? void 0 : _f$geometry.type) !== null && _f$geometry$type !== void 0 ? _f$geometry$type : '');
  })) {
    throw new Error('Overview network must contain line features.');
  }
}
var equalPoint = function equalPoint(a, b) {
  return a.length === b.length && a.every(function (v, i) {
    return Math.abs(v - b[i]) < 1e-12;
  });
};
function lineBounds(coordinates) {
  return [Math.min.apply(Math, _toConsumableArray(coordinates.map(function (p) {
    return p[0];
  }))), Math.min.apply(Math, _toConsumableArray(coordinates.map(function (p) {
    return p[1];
  }))), Math.max.apply(Math, _toConsumableArray(coordinates.map(function (p) {
    return p[0];
  }))), Math.max.apply(Math, _toConsumableArray(coordinates.map(function (p) {
    return p[1];
  })))];
}
/** Bucket rectangular tiles once so full-area linework only checks nearby tiles. */
function tileLookup(tiles) {
  if (!tiles.length) return function (_bounds) {
    return [];
  };
  var originX = Math.min.apply(Math, _toConsumableArray(tiles.map(function (tile) {
    return tile.bounds[0];
  })));
  var originY = Math.min.apply(Math, _toConsumableArray(tiles.map(function (tile) {
    return tile.bounds[1];
  })));
  var width = Math.max(1e-12, Math.min.apply(Math, _toConsumableArray(tiles.map(function (tile) {
    return tile.bounds[2] - tile.bounds[0];
  }))));
  var height = Math.max(1e-12, Math.min.apply(Math, _toConsumableArray(tiles.map(function (tile) {
    return tile.bounds[3] - tile.bounds[1];
  }))));
  var buckets = new Map();
  var cells = function cells(bounds) {
    var epsilon = 1e-12;
    var x0 = Math.floor((bounds[0] - epsilon - originX) / width);
    var x1 = Math.floor((bounds[2] + epsilon - originX) / width);
    var y0 = Math.floor((bounds[1] - epsilon - originY) / height);
    var y1 = Math.floor((bounds[3] + epsilon - originY) / height);
    var result = [];
    for (var x = x0; x <= x1; x++) for (var y = y0; y <= y1; y++) result.push("".concat(x, ":").concat(y));
    return result;
  };
  var _iterator2 = _createForOfIteratorHelper(tiles),
    _step2;
  try {
    for (_iterator2.s(); !(_step2 = _iterator2.n()).done;) {
      var tile = _step2.value;
      var _iterator5 = _createForOfIteratorHelper(cells(tile.bounds)),
        _step5;
      try {
        for (_iterator5.s(); !(_step5 = _iterator5.n()).done;) {
          var _buckets$get2;
          var cell = _step5.value;
          var bucket = (_buckets$get2 = buckets.get(cell)) !== null && _buckets$get2 !== void 0 ? _buckets$get2 : [];
          bucket.push(tile);
          buckets.set(cell, bucket);
        }
      } catch (err) {
        _iterator5.e(err);
      } finally {
        _iterator5.f();
      }
    }
  } catch (err) {
    _iterator2.e(err);
  } finally {
    _iterator2.f();
  }
  return function (bounds) {
    var found = new Map();
    var _iterator3 = _createForOfIteratorHelper(cells(bounds)),
      _step3;
    try {
      for (_iterator3.s(); !(_step3 = _iterator3.n()).done;) {
        var _buckets$get;
        var cell = _step3.value;
        var _iterator4 = _createForOfIteratorHelper((_buckets$get = buckets.get(cell)) !== null && _buckets$get !== void 0 ? _buckets$get : []),
          _step4;
        try {
          for (_iterator4.s(); !(_step4 = _iterator4.n()).done;) {
            var tile = _step4.value;
            var b = tile.bounds;
            if (b[0] <= bounds[2] + 1e-12 && b[2] >= bounds[0] - 1e-12 && b[1] <= bounds[3] + 1e-12 && b[3] >= bounds[1] - 1e-12) found.set(tile.id, tile);
          }
        } catch (err) {
          _iterator4.e(err);
        } finally {
          _iterator4.f();
        }
      }
    } catch (err) {
      _iterator3.e(err);
    } finally {
      _iterator3.f();
    }
    return _toConsumableArray(found.values()).sort(function (a, b) {
      return a.id.localeCompare(b.id);
    });
  };
}
function splitLine(coordinates, tiles, keep) {
  var parts = [];
  var active = [];
  var removed = false;
  var flush = function flush() {
    if (active.length > 1) parts.push(active);
    active = [];
  };
  var _loop2 = function _loop2() {
    var a = coordinates[i - 1],
      b = coordinates[i];
    var cuts = new Set([0, 1]);
    var _iterator6 = _createForOfIteratorHelper(tiles),
      _step6;
    try {
      for (_iterator6.s(); !(_step6 = _iterator6.n()).done;) {
        var bounds = _step6.value.bounds;
        for (var _i2 = 0, _arr = [0, 1]; _i2 < _arr.length; _i2++) {
          var axis = _arr[_i2];
          if (b[axis] === a[axis]) continue;
          for (var _i3 = 0, _arr2 = [bounds[axis], bounds[axis + 2]]; _i3 < _arr2.length; _i3++) {
            var edge = _arr2[_i3];
            var t = (edge - a[axis]) / (b[axis] - a[axis]);
            if (t > 0 && t < 1) cuts.add(t);
          }
        }
      }
    } catch (err) {
      _iterator6.e(err);
    } finally {
      _iterator6.f();
    }
    var sorted = _toConsumableArray(cuts).sort(function (x, y) {
      return x - y;
    });
    var point = function point(t) {
      return t === 0 ? a : t === 1 ? b : a.map(function (v, axis) {
        return v + t * (b[axis] - v);
      });
    };
    var _loop3 = function _loop3() {
        var _tiles$find;
        var start = point(sorted[j - 1]),
          end = point(sorted[j]);
        if (equalPoint(start, end)) return 0; // continue
        var midpoint = [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2];
        // Shared-border line segments belong to the lexicographically first tile.
        var owner = (_tiles$find = tiles.find(function (_ref) {
          var q = _ref.bounds;
          return midpoint[0] >= q[0] - 1e-12 && midpoint[0] <= q[2] + 1e-12 && midpoint[1] >= q[1] - 1e-12 && midpoint[1] <= q[3] + 1e-12;
        })) === null || _tiles$find === void 0 ? void 0 : _tiles$find.id;
        if (!keep(owner)) {
          removed = true;
          flush();
          return 0; // continue
        }
        if (active.length && !equalPoint(active[active.length - 1], start)) flush();
        if (!active.length) active = [start];
        active.push(end);
      },
      _ret;
    for (var j = 1; j < sorted.length; j++) {
      _ret = _loop3();
      if (_ret === 0) continue;
    }
  };
  for (var i = 1; i < coordinates.length; i++) {
    _loop2();
  }
  flush();
  return {
    parts: parts,
    removed: removed
  };
}
function lines(feature) {
  var _feature$geometry, _feature$geometry2;
  return ((_feature$geometry = feature.geometry) === null || _feature$geometry === void 0 ? void 0 : _feature$geometry.type) === 'MultiLineString' ? feature.geometry.coordinates : ((_feature$geometry2 = feature.geometry) === null || _feature$geometry2 === void 0 ? void 0 : _feature$geometry2.type) === 'LineString' ? [feature.geometry.coordinates] : [];
}

// autk-db's default metric workspace reduces geometry to a 0.01 m grid.
// Tile clipping can create fragments smaller than one grid-cell diagonal;
// those collapse on import and prevent the entire After layer from loading.
// Keep the committed network and provenance exact; omit only such generated
// fragments from the derived overview display.
function renderableFragment(coordinates) {
  if (coordinates.length < 2) return false;
  var lat = coordinates.reduce(function (sum, point) {
    return sum + point[1];
  }, 0) / coordinates.length;
  var xScale = 111320 * Math.cos(lat * Math.PI / 180);
  var yScale = 111320;
  var xs = coordinates.map(function (point) {
    return point[0];
  });
  var ys = coordinates.map(function (point) {
    return point[1];
  });
  return Math.hypot((Math.max.apply(Math, _toConsumableArray(xs)) - Math.min.apply(Math, _toConsumableArray(xs))) * xScale, (Math.max.apply(Math, _toConsumableArray(ys)) - Math.min.apply(Math, _toConsumableArray(ys))) * yScale) >= 0.015;
}

/** Replace owned portions of original linework; committed empty tiles are deletions. */
function buildOverview(context, config, latestTileOutput) {
  validateOverview(context);
  var tiles = context.grid.features.map(function (tile) {
    var _tile$properties2;
    return {
      id: String((_tile$properties2 = tile.properties) === null || _tile$properties2 === void 0 ? void 0 : _tile$properties2.tile_id),
      bounds: (0,_sidewalkEditOperations__WEBPACK_IMPORTED_MODULE_0__.featureBounds)(tile)
    };
  }).sort(function (a, b) {
    return a.id.localeCompare(b.id);
  });
  var edits = tiles.flatMap(function (tile) {
    var record = savedTile(config, tile.id);
    return record !== null && record !== void 0 && record.committedNetwork ? [_objectSpread(_objectSpread({}, tile), {}, {
      record: record
    })] : [];
  });
  var committedIds = new Set(edits.map(function (e) {
    return e.id;
  }));
  var nearbyTiles = tileLookup(tiles);
  var nearbyEdits = tileLookup(edits);
  var features = [];
  var _iterator7 = _createForOfIteratorHelper(context.network.features.entries()),
    _step7;
  try {
    var _loop4 = function _loop4() {
        var _step7$value = _slicedToArray(_step7.value, 2),
          index = _step7$value[0],
          feature = _step7$value[1];
        var sourceLines = lines(feature);
        if (!sourceLines.some(function (line) {
          return nearbyEdits(lineBounds(line)).length;
        })) {
          features.push(feature);
          return 0; // continue
        }
        var split = sourceLines.map(function (line) {
          return splitLine(line, nearbyTiles(lineBounds(line)), function (owner) {
            return !owner || !committedIds.has(owner);
          });
        });
        if (!split.some(function (s) {
          return s.removed;
        })) {
          features.push(feature);
          return 0; // continue
        }
        split.flatMap(function (s) {
          return s.parts;
        }).filter(renderableFragment).forEach(function (coordinates, part) {
          var _feature$id;
          return features.push(_objectSpread(_objectSpread({}, feature), {}, {
            id: "base:".concat(String((_feature$id = feature.id) !== null && _feature$id !== void 0 ? _feature$id : index), ":").concat(index, ":outside:").concat(part),
            geometry: {
              type: 'LineString',
              coordinates: coordinates
            }
          }));
        });
      },
      _ret2;
    for (_iterator7.s(); !(_step7 = _iterator7.n()).done;) {
      _ret2 = _loop4();
      if (_ret2 === 0) continue;
    }
  } catch (err) {
    _iterator7.e(err);
  } finally {
    _iterator7.f();
  }
  var _iterator8 = _createForOfIteratorHelper(edits),
    _step8;
  try {
    var _loop5 = function _loop5() {
      var _step8$value = _step8.value,
        id = _step8$value.id,
        record = _step8$value.record;
      record.committedNetwork.features.forEach(function (feature, index) {
        lines(feature).flatMap(function (line) {
          return splitLine(line, nearbyTiles(lineBounds(line)), function (owner) {
            return owner === id;
          }).parts;
        }).filter(renderableFragment).forEach(function (coordinates, part) {
          var _feature$properties$h, _feature$properties3, _record$revision2, _feature$id2;
          features.push(_objectSpread(_objectSpread({}, feature), {}, {
            id: "saved:".concat(config.overview.datasetId, ":").concat(id, ":").concat(index, ":").concat(part),
            geometry: {
              type: 'LineString',
              coordinates: coordinates
            },
            properties: _objectSpread(_objectSpread({}, feature.properties), {}, {
              // AutkMap's supported roads classification gives new sidewalk edges the same thin path style.
              highway: (_feature$properties$h = (_feature$properties3 = feature.properties) === null || _feature$properties3 === void 0 ? void 0 : _feature$properties3.highway) !== null && _feature$properties$h !== void 0 ? _feature$properties$h : 'path',
              tile_id: id,
              sidewalk_dataset_id: config.overview.datasetId,
              sidewalk_edit_revision: (_record$revision2 = record.revision) !== null && _record$revision2 !== void 0 ? _record$revision2 : 1,
              sidewalk_source_feature_id: (_feature$id2 = feature.id) !== null && _feature$id2 !== void 0 ? _feature$id2 : index,
              sidewalk_provenance_ref: id
            })
          }));
        });
      });
    };
    for (_iterator8.s(); !(_step8 = _iterator8.n()).done;) {
      _loop5();
    }
  } catch (err) {
    _iterator8.e(err);
  } finally {
    _iterator8.f();
  }
  var grid = _objectSpread(_objectSpread({}, context.grid), {}, {
    features: context.grid.features.map(function (feature) {
      var _feature$properties2;
      var _ref2 = (_feature$properties2 = feature.properties) !== null && _feature$properties2 !== void 0 ? _feature$properties2 : {},
        _selection = _ref2.interacted,
        properties = _objectWithoutProperties(_ref2, _excluded);
      return _objectSpread(_objectSpread({}, feature), {}, {
        properties: properties
      });
    })
  });
  return {
    dataType: 'outputs',
    data: [{
      dataType: 'geodataframe',
      layerName: 'upstream',
      layerType: 'polygons',
      data: grid
    }, {
      dataType: 'geodataframe',
      layerName: 'sidewalk_network',
      layerType: 'roads',
      data: _objectSpread(_objectSpread({}, context.network), {}, {
        features: features
      })
    }, {
      dataType: 'geodataframe',
      layerName: 'tile_boundaries',
      layerType: 'polylines',
      data: context.boundaries
    }],
    metadata: _objectSpread({
      datasetId: config.overview.datasetId,
      datasetIdentity: overviewIdentity(config),
      committedEdits: Object.fromEntries(edits.map(function (_ref3) {
        var _record$revision;
        var id = _ref3.id,
          record = _ref3.record;
        return [id, {
          editRevision: (_record$revision = record.revision) !== null && _record$revision !== void 0 ? _record$revision : 1,
          provenance: record.provenance,
          envelope: record.committedEdit
        }];
      }))
    }, latestTileOutput ? {
      latestTileOutput: latestTileOutput
    } : {})
  };
}

/***/ },

/***/ "../../../packages/curio.sidewalk-stewards@1/sources/provenance.ts"
/*!*************************************************************************!*\
  !*** ../../../packages/curio.sidewalk-stewards@1/sources/provenance.ts ***!
  \*************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   buildEditProvenance: () => (/* binding */ buildEditProvenance),
/* harmony export */   geometryHash: () => (/* binding */ geometryHash)
/* harmony export */ });
function _toConsumableArray(r) { return _arrayWithoutHoles(r) || _iterableToArray(r) || _unsupportedIterableToArray(r) || _nonIterableSpread(); }
function _nonIterableSpread() { throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _iterableToArray(r) { if ("undefined" != typeof Symbol && null != r[Symbol.iterator] || null != r["@@iterator"]) return Array.from(r); }
function _arrayWithoutHoles(r) { if (Array.isArray(r)) return _arrayLikeToArray(r); }
function _slicedToArray(r, e) { return _arrayWithHoles(r) || _iterableToArrayLimit(r, e) || _unsupportedIterableToArray(r, e) || _nonIterableRest(); }
function _nonIterableRest() { throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
function _iterableToArrayLimit(r, l) { var t = null == r ? null : "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (null != t) { var e, n, i, u, a = [], f = !0, o = !1; try { if (i = (t = t.call(r)).next, 0 === l) { if (Object(t) !== t) return; f = !1; } else for (; !(f = (e = i.call(t)).done) && (a.push(e.value), a.length !== l); f = !0); } catch (r) { o = !0, n = r; } finally { try { if (!f && null != t["return"] && (u = t["return"](), Object(u) !== u)) return; } finally { if (o) throw n; } } return a; } }
function _arrayWithHoles(r) { if (Array.isArray(r)) return r; }
function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
var stable = function stable(value) {
  return JSON.stringify(value, function (_key, item) {
    if (!item || Array.isArray(item) || _typeof(item) !== 'object') return item;
    return Object.fromEntries(Object.entries(item).sort(function (_ref, _ref2) {
      var _ref3 = _slicedToArray(_ref, 1),
        a = _ref3[0];
      var _ref4 = _slicedToArray(_ref2, 1),
        b = _ref4[0];
      return a.localeCompare(b);
    }));
  });
};

/** Deterministic lightweight source fingerprint when no source revision exists. */
function geometryHash(collection) {
  var input = stable(collection);
  var hash = 2166136261;
  for (var i = 0; i < input.length; i += 1) hash = Math.imul(hash ^ input.charCodeAt(i), 16777619);
  return "fnv1a32:".concat((hash >>> 0).toString(16).padStart(8, '0'));
}
function idOf(feature, index) {
  var _ref5, _ref6, _feature$id, _feature$properties, _feature$properties2;
  return String((_ref5 = (_ref6 = (_feature$id = feature.id) !== null && _feature$id !== void 0 ? _feature$id : (_feature$properties = feature.properties) === null || _feature$properties === void 0 ? void 0 : _feature$properties.feature_id) !== null && _ref6 !== void 0 ? _ref6 : (_feature$properties2 = feature.properties) === null || _feature$properties2 === void 0 ? void 0 : _feature$properties2.id) !== null && _ref5 !== void 0 ? _ref5 : "row:".concat(index));
}
function buildEditProvenance(args) {
  var _args$sourceRevision;
  var beforeById = new Map(args.before.features.map(function (feature, index) {
    return [idOf(feature, index), stable(feature.geometry)];
  }));
  var afterById = new Map(args.after.features.map(function (feature, index) {
    return [idOf(feature, index), stable(feature.geometry)];
  }));
  var affectedFeatureIds = _toConsumableArray(new Set([].concat(_toConsumableArray(beforeById.keys()), _toConsumableArray(afterById.keys())))).filter(function (id) {
    return beforeById.get(id) !== afterById.get(id);
  }).sort();
  return {
    schema: 'io.github.lzml0.sidewalk-stewards/provenance',
    version: 1,
    selectedTileId: args.tileId,
    operations: args.operations.map(function (type, index) {
      return {
        sequence: index + 1,
        type: type
      };
    }),
    affectedFeatureIds: affectedFeatureIds,
    sourceRevision: (_args$sourceRevision = args.sourceRevision) !== null && _args$sourceRevision !== void 0 ? _args$sourceRevision : geometryHash(args.before),
    before: args.before,
    after: args.after,
    editRevision: args.editRevision,
    timestamp: new Date().toISOString(),
    validationWarnings: _toConsumableArray(args.validationWarnings)
  };
}

/***/ },

/***/ "../../../packages/curio.sidewalk-stewards@1/sources/resourceResolver.ts"
/*!*******************************************************************************!*\
  !*** ../../../packages/curio.sidewalk-stewards@1/sources/resourceResolver.ts ***!
  \*******************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   assetUrl: () => (/* binding */ assetUrl),
/* harmony export */   fetchData: () => (/* binding */ fetchData)
/* harmony export */ });
function _regenerator() { /*! regenerator-runtime -- Copyright (c) 2014-present, Facebook, Inc. -- license (MIT): https://github.com/babel/babel/blob/main/packages/babel-helpers/LICENSE */ var e, t, r = "function" == typeof Symbol ? Symbol : {}, n = r.iterator || "@@iterator", o = r.toStringTag || "@@toStringTag"; function i(r, n, o, i) { var c = n && n.prototype instanceof Generator ? n : Generator, u = Object.create(c.prototype); return _regeneratorDefine2(u, "_invoke", function (r, n, o) { var i, c, u, f = 0, p = o || [], y = !1, G = { p: 0, n: 0, v: e, a: d, f: d.bind(e, 4), d: function d(t, r) { return i = t, c = 0, u = e, G.n = r, a; } }; function d(r, n) { for (c = r, u = n, t = 0; !y && f && !o && t < p.length; t++) { var o, i = p[t], d = G.p, l = i[2]; r > 3 ? (o = l === n) && (u = i[(c = i[4]) ? 5 : (c = 3, 3)], i[4] = i[5] = e) : i[0] <= d && ((o = r < 2 && d < i[1]) ? (c = 0, G.v = n, G.n = i[1]) : d < l && (o = r < 3 || i[0] > n || n > l) && (i[4] = r, i[5] = n, G.n = l, c = 0)); } if (o || r > 1) return a; throw y = !0, n; } return function (o, p, l) { if (f > 1) throw TypeError("Generator is already running"); for (y && 1 === p && d(p, l), c = p, u = l; (t = c < 2 ? e : u) || !y;) { i || (c ? c < 3 ? (c > 1 && (G.n = -1), d(c, u)) : G.n = u : G.v = u); try { if (f = 2, i) { if (c || (o = "next"), t = i[o]) { if (!(t = t.call(i, u))) throw TypeError("iterator result is not an object"); if (!t.done) return t; u = t.value, c < 2 && (c = 0); } else 1 === c && (t = i["return"]) && t.call(i), c < 2 && (u = TypeError("The iterator does not provide a '" + o + "' method"), c = 1); i = e; } else if ((t = (y = G.n < 0) ? u : r.call(n, G)) !== a) break; } catch (t) { i = e, c = 1, u = t; } finally { f = 1; } } return { value: t, done: y }; }; }(r, o, i), !0), u; } var a = {}; function Generator() {} function GeneratorFunction() {} function GeneratorFunctionPrototype() {} t = Object.getPrototypeOf; var c = [][n] ? t(t([][n]())) : (_regeneratorDefine2(t = {}, n, function () { return this; }), t), u = GeneratorFunctionPrototype.prototype = Generator.prototype = Object.create(c); function f(e) { return Object.setPrototypeOf ? Object.setPrototypeOf(e, GeneratorFunctionPrototype) : (e.__proto__ = GeneratorFunctionPrototype, _regeneratorDefine2(e, o, "GeneratorFunction")), e.prototype = Object.create(u), e; } return GeneratorFunction.prototype = GeneratorFunctionPrototype, _regeneratorDefine2(u, "constructor", GeneratorFunctionPrototype), _regeneratorDefine2(GeneratorFunctionPrototype, "constructor", GeneratorFunction), GeneratorFunction.displayName = "GeneratorFunction", _regeneratorDefine2(GeneratorFunctionPrototype, o, "GeneratorFunction"), _regeneratorDefine2(u), _regeneratorDefine2(u, o, "Generator"), _regeneratorDefine2(u, n, function () { return this; }), _regeneratorDefine2(u, "toString", function () { return "[object Generator]"; }), (_regenerator = function _regenerator() { return { w: i, m: f }; })(); }
function _regeneratorDefine2(e, r, n, t) { var i = Object.defineProperty; try { i({}, "", {}); } catch (e) { i = 0; } _regeneratorDefine2 = function _regeneratorDefine(e, r, n, t) { function o(r, n) { _regeneratorDefine2(e, r, function (e) { return this._invoke(r, n, e); }); } r ? i ? i(e, r, { value: n, enumerable: !t, configurable: !t, writable: !t }) : e[r] = n : (o("next", 0), o("throw", 1), o("return", 2)); }, _regeneratorDefine2(e, r, n, t); }
function asyncGeneratorStep(n, t, e, r, o, a, c) { try { var i = n[a](c), u = i.value; } catch (n) { return void e(n); } i.done ? t(u) : Promise.resolve(u).then(r, o); }
function _asyncToGenerator(n) { return function () { var t = this, e = arguments; return new Promise(function (r, o) { var a = n.apply(t, e); function _next(n) { asyncGeneratorStep(a, r, o, _next, _throw, "next", n); } function _throw(n) { asyncGeneratorStep(a, r, o, _next, _throw, "throw", n); } _next(void 0); }); }; }
/** Package-local access to Curio's existing artifact and file endpoints. */
function backendUrl() {
  var _curio;
  return typeof window !== 'undefined' && ((_curio = window.curio) === null || _curio === void 0 ? void 0 : _curio.backendUrl) || 'http://localhost:5002';
}
function authHeaders() {
  if (typeof document === 'undefined') return {};
  var match = document.cookie.match(/(?:^|;\s*)session_token=([^;]*)/);
  return match ? {
    Authorization: "Bearer ".concat(decodeURIComponent(match[1]))
  } : {};
}
function fetchData(_x, _x2) {
  return _fetchData.apply(this, arguments);
}
function _fetchData() {
  _fetchData = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee(reference, signal) {
    var response;
    return _regenerator().w(function (_context) {
      while (1) switch (_context.n) {
        case 0:
          _context.n = 1;
          return fetch("".concat(backendUrl(), "/get?fileName=").concat(encodeURIComponent(reference)), {
            headers: authHeaders(),
            signal: signal
          });
        case 1:
          response = _context.v;
          if (response.ok) {
            _context.n = 2;
            break;
          }
          throw new Error("Could not read upstream spatial data (HTTP ".concat(response.status, ")."));
        case 2:
          return _context.a(2, response.json());
      }
    }, _callee);
  }));
  return _fetchData.apply(this, arguments);
}
function assetUrl(path) {
  if (/^(https?:|data:|blob:)/i.test(path)) return path;
  return "".concat(backendUrl(), "/file/").concat(path.replace(/^\/+/, ''));
}

/***/ },

/***/ "../../../packages/curio.sidewalk-stewards@1/sources/selectedResources.ts"
/*!********************************************************************************!*\
  !*** ../../../packages/curio.sidewalk-stewards@1/sources/selectedResources.ts ***!
  \********************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   resolveSelectedGeojsonSources: () => (/* binding */ resolveSelectedGeojsonSources),
/* harmony export */   resolveSelectedResourceTemplate: () => (/* binding */ resolveSelectedResourceTemplate)
/* harmony export */ });
function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
var _excluded = ["geojsonFileUrlTemplate"];
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: !0, configurable: !0, writable: !0 }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == _typeof(i) ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != _typeof(t) || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r || "default"); if ("object" != _typeof(i)) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
function _objectWithoutProperties(e, t) { if (null == e) return {}; var o, r, i = _objectWithoutPropertiesLoose(e, t); if (Object.getOwnPropertySymbols) { var n = Object.getOwnPropertySymbols(e); for (r = 0; r < n.length; r++) o = n[r], -1 === t.indexOf(o) && {}.propertyIsEnumerable.call(e, o) && (i[o] = e[o]); } return i; }
function _objectWithoutPropertiesLoose(r, e) { if (null == r) return {}; var t = {}; for (var n in r) if ({}.hasOwnProperty.call(r, n)) { if (-1 !== e.indexOf(n)) continue; t[n] = r[n]; } return t; }
/** Resolve a prepared resource path from one selected upstream feature. */
function resolveSelectedResourceTemplate(template, selection) {
  var _selection$features$;
  if (!template.trim()) throw new Error('An explicit image or network resource path is required. Connect Sidewalk Prepare or configure the resource template.');
  var properties = (_selection$features$ = selection.features[0]) === null || _selection$features$ === void 0 ? void 0 : _selection$features$.properties;
  if (!properties) throw new Error('A selected spatial feature is required to load this resource.');
  return template.replace(/\{([a-zA-Z][a-zA-Z0-9_]*)\}/g, function (_token, key) {
    var value = properties[key];
    if (typeof value !== 'string' && typeof value !== 'number' || !/^[a-zA-Z0-9_-]+$/.test(String(value))) {
      throw new Error("Selected feature has no safe ".concat(key, " value for the resource path."));
    }
    return encodeURIComponent(String(value));
  });
}

/** Curio extension: load a prepared GeoJSON file for the selected region/tile. */
function resolveSelectedGeojsonSources(sources, selection) {
  return sources.map(function (source) {
    if (typeof source.geojsonFileUrlTemplate !== 'string') return source;
    if (!selection) throw new Error('Select a region or tile before loading its spatial layers.');
    var geojsonFileUrlTemplate = source.geojsonFileUrlTemplate,
      rest = _objectWithoutProperties(source, _excluded);
    return _objectSpread(_objectSpread({}, rest), {}, {
      geojsonFileUrl: resolveSelectedResourceTemplate(geojsonFileUrlTemplate, selection)
    });
  });
}

/***/ },

/***/ "../../../packages/curio.sidewalk-stewards@1/sources/sidewalkEditOperations.ts"
/*!*************************************************************************************!*\
  !*** ../../../packages/curio.sidewalk-stewards@1/sources/sidewalkEditOperations.ts ***!
  \*************************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   clipNetworkToBounds: () => (/* binding */ clipNetworkToBounds),
/* harmony export */   connectNetworkNodes: () => (/* binding */ connectNetworkNodes),
/* harmony export */   deleteNetworkNode: () => (/* binding */ deleteNetworkNode),
/* harmony export */   deleteNetworkNodesInBounds: () => (/* binding */ deleteNetworkNodesInBounds),
/* harmony export */   drawNetworkEdge: () => (/* binding */ drawNetworkEdge),
/* harmony export */   endpointNodes: () => (/* binding */ endpointNodes),
/* harmony export */   featureBounds: () => (/* binding */ featureBounds),
/* harmony export */   moveNetworkNode: () => (/* binding */ moveNetworkNode),
/* harmony export */   networkNodes: () => (/* binding */ networkNodes),
/* harmony export */   removeNetworkInsideBounds: () => (/* binding */ removeNetworkInsideBounds),
/* harmony export */   splitNetworkEdge: () => (/* binding */ splitNetworkEdge),
/* harmony export */   validateNetwork: () => (/* binding */ validateNetwork)
/* harmony export */ });
function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: !0, configurable: !0, writable: !0 }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == _typeof(i) ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != _typeof(t) || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r || "default"); if ("object" != _typeof(i)) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
function _createForOfIteratorHelper(r, e) { var t = "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (!t) { if (Array.isArray(r) || (t = _unsupportedIterableToArray(r)) || e && r && "number" == typeof r.length) { t && (r = t); var _n = 0, F = function F() {}; return { s: F, n: function n() { return _n >= r.length ? { done: !0 } : { done: !1, value: r[_n++] }; }, e: function e(r) { throw r; }, f: F }; } throw new TypeError("Invalid attempt to iterate non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); } var o, a = !0, u = !1; return { s: function s() { t = t.call(r); }, n: function n() { var r = t.next(); return a = r.done, r; }, e: function e(r) { u = !0, o = r; }, f: function f() { try { a || null == t["return"] || t["return"](); } finally { if (u) throw o; } } }; }
function _slicedToArray(r, e) { return _arrayWithHoles(r) || _iterableToArrayLimit(r, e) || _unsupportedIterableToArray(r, e) || _nonIterableRest(); }
function _nonIterableRest() { throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _iterableToArrayLimit(r, l) { var t = null == r ? null : "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (null != t) { var e, n, i, u, a = [], f = !0, o = !1; try { if (i = (t = t.call(r)).next, 0 === l) { if (Object(t) !== t) return; f = !1; } else for (; !(f = (e = i.call(t)).done) && (a.push(e.value), a.length !== l); f = !0); } catch (r) { o = !0, n = r; } finally { try { if (!f && null != t["return"] && (u = t["return"](), Object(u) !== u)) return; } finally { if (o) throw n; } } return a; } }
function _arrayWithHoles(r) { if (Array.isArray(r)) return r; }
function _toConsumableArray(r) { return _arrayWithoutHoles(r) || _iterableToArray(r) || _unsupportedIterableToArray(r) || _nonIterableSpread(); }
function _nonIterableSpread() { throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _iterableToArray(r) { if ("undefined" != typeof Symbol && null != r[Symbol.iterator] || null != r["@@iterator"]) return Array.from(r); }
function _arrayWithoutHoles(r) { if (Array.isArray(r)) return _arrayLikeToArray(r); }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
var round = function round(n) {
  return Math.round(n * 1e8) / 1e8;
};
var pointKey = function pointKey(p) {
  return "".concat(round(p[0]), ",").concat(round(p[1]));
};
function featureBounds(feature) {
  if (!(feature !== null && feature !== void 0 && feature.geometry) || !('coordinates' in feature.geometry)) return null;
  var coords = [];
  var _visit = function visit(value) {
    if (!Array.isArray(value)) return;
    if (typeof value[0] === 'number' && typeof value[1] === 'number') {
      coords.push(value);
      return;
    }
    value.forEach(_visit);
  };
  _visit(feature.geometry.coordinates);
  if (!coords.length) return null;
  return [Math.min.apply(Math, _toConsumableArray(coords.map(function (p) {
    return p[0];
  }))), Math.min.apply(Math, _toConsumableArray(coords.map(function (p) {
    return p[1];
  }))), Math.max.apply(Math, _toConsumableArray(coords.map(function (p) {
    return p[0];
  }))), Math.max.apply(Math, _toConsumableArray(coords.map(function (p) {
    return p[1];
  })))];
}

/** Liang–Barsky clipping of one segment to a tile's rectangular bounds. */
function clipSegment(a, b, bounds) {
  var _bounds = _slicedToArray(bounds, 4),
    xmin = _bounds[0],
    ymin = _bounds[1],
    xmax = _bounds[2],
    ymax = _bounds[3];
  var dx = b[0] - a[0];
  var dy = b[1] - a[1];
  var lo = 0;
  var hi = 1;
  var tests = [[-dx, a[0] - xmin], [dx, xmax - a[0]], [-dy, a[1] - ymin], [dy, ymax - a[1]]];
  for (var _i = 0, _tests = tests; _i < _tests.length; _i++) {
    var _tests$_i = _slicedToArray(_tests[_i], 2),
      p = _tests$_i[0],
      q = _tests$_i[1];
    if (p === 0) {
      if (q < 0) return null;
      continue;
    }
    var t = q / p;
    if (p < 0) lo = Math.max(lo, t);else hi = Math.min(hi, t);
    if (lo > hi) return null;
  }
  return [[a[0] + lo * dx, a[1] + lo * dy], [a[0] + hi * dx, a[1] + hi * dy]];
}

/** Clip line features to a selected tile and preserve their properties/IDs. */
function clipNetworkToBounds(fc, bounds) {
  var features = [];
  var _iterator = _createForOfIteratorHelper(fc.features),
    _step;
  try {
    var _loop = function _loop() {
      var feature = _step.value;
      var geometry = feature.geometry;
      if (!geometry || geometry.type !== 'LineString') return 1; // continue
      var parts = [];
      var active = [];
      for (var i = 1; i < geometry.coordinates.length; i += 1) {
        var segment = clipSegment(geometry.coordinates[i - 1], geometry.coordinates[i], bounds);
        if (!segment) {
          if (active.length > 1) parts.push(active);
          active = [];
          continue;
        }
        var _segment = _slicedToArray(segment, 2),
          a = _segment[0],
          b = _segment[1];
        if (!active.length || pointKey(active[active.length - 1]) !== pointKey(a)) {
          if (active.length > 1) parts.push(active);
          active = [a];
        }
        if (pointKey(active[active.length - 1]) !== pointKey(b)) active.push(b);
      }
      if (active.length > 1) parts.push(active);
      parts.forEach(function (coordinates, partIndex) {
        var _feature$id;
        features.push(_objectSpread(_objectSpread(_objectSpread({}, feature), parts.length > 1 ? {
          id: "".concat(String((_feature$id = feature.id) !== null && _feature$id !== void 0 ? _feature$id : "feature-".concat(features.length)), ":clip-").concat(partIndex)
        } : {}), {}, {
          geometry: {
            type: 'LineString',
            coordinates: coordinates
          }
        }));
      });
    };
    for (_iterator.s(); !(_step = _iterator.n()).done;) {
      if (_loop()) continue;
    }
  } catch (err) {
    _iterator.e(err);
  } finally {
    _iterator.f();
  }
  return _objectSpread(_objectSpread({}, fc), {}, {
    features: features
  });
}

/** Keep only the parts of linework outside a tile rectangle. Used when an
 * edited tile replaces its old linework in a larger overview network. */
function removeNetworkInsideBounds(fc, bounds) {
  var features = [];
  var _iterator2 = _createForOfIteratorHelper(fc.features),
    _step2;
  try {
    var _loop2 = function _loop2() {
      var _feature$geometry;
      var feature = _step2.value;
      if (((_feature$geometry = feature.geometry) === null || _feature$geometry === void 0 ? void 0 : _feature$geometry.type) !== 'LineString') {
        features.push(feature);
        return 1; // continue
      }
      var parts = [];
      var active = [];
      var flush = function flush() {
        if (active.length > 1) parts.push(active);
        active = [];
      };
      for (var i = 1; i < feature.geometry.coordinates.length; i += 1) {
        var a = feature.geometry.coordinates[i - 1];
        var b = feature.geometry.coordinates[i];
        var clipped = clipSegment(a, b, bounds);
        if (!clipped) {
          if (!active.length) active = [a];
          if (pointKey(active[active.length - 1]) !== pointKey(b)) active.push(b);
          continue;
        }
        var _clipped = _slicedToArray(clipped, 2),
          insideA = _clipped[0],
          insideB = _clipped[1];
        var startsInside = pointKey(a) === pointKey(insideA);
        var endsInside = pointKey(b) === pointKey(insideB);
        if (startsInside) flush();else {
          if (!active.length) active = [a];
          if (pointKey(active[active.length - 1]) !== pointKey(insideA)) active.push(insideA);
          flush();
        }
        if (endsInside) flush();else {
          active = [insideB];
          if (pointKey(active[active.length - 1]) !== pointKey(b)) active.push(b);
        }
      }
      flush();
      parts.forEach(function (coordinates, partIndex) {
        var _feature$id2;
        return features.push(_objectSpread(_objectSpread(_objectSpread({}, feature), parts.length > 1 ? {
          id: "".concat(String((_feature$id2 = feature.id) !== null && _feature$id2 !== void 0 ? _feature$id2 : "feature-".concat(features.length)), ":outside-").concat(partIndex)
        } : {}), {}, {
          geometry: {
            type: 'LineString',
            coordinates: coordinates
          }
        }));
      });
    };
    for (_iterator2.s(); !(_step2 = _iterator2.n()).done;) {
      if (_loop2()) continue;
    }
  } catch (err) {
    _iterator2.e(err);
  } finally {
    _iterator2.f();
  }
  return _objectSpread(_objectSpread({}, fc), {}, {
    features: features
  });
}
function isLineFeature(feature) {
  var _feature$geometry2;
  return ((_feature$geometry2 = feature.geometry) === null || _feature$geometry2 === void 0 ? void 0 : _feature$geometry2.type) === 'LineString';
}
function moveNetworkNode(fc, from, to) {
  var features = fc.features.flatMap(function (feature) {
    if (!isLineFeature(feature)) return [feature];
    var changed = false;
    var coordinates = feature.geometry.coordinates.reduce(function (result, position) {
      var next = pointKey(position) === pointKey(from) ? [to[0], to[1]].concat(_toConsumableArray(position.slice(2))) : position;
      if (next !== position) changed = true;
      if (!result.length || pointKey(result[result.length - 1]) !== pointKey(next)) result.push(next);else changed = true;
      return result;
    }, []);
    // Dropping a node onto the opposite end of a two-node edge can collapse
    // that edge to a self-loop. Joining graph nodes should not leave invalid
    // zero-length features behind.
    if (coordinates.length < 2 || new Set(coordinates.map(pointKey)).size < 2) return [];
    if (!changed) return [feature];
    return [_objectSpread(_objectSpread({}, feature), {}, {
      geometry: _objectSpread(_objectSpread({}, feature.geometry), {}, {
        coordinates: coordinates
      })
    })];
  });
  return _objectSpread(_objectSpread({}, fc), {}, {
    features: features
  });
}
function drawNetworkEdge(fc, coordinates) {
  if (coordinates.length < 2) return fc;
  var feature = {
    type: 'Feature',
    id: "curio-sidewalk-edge-".concat(Date.now(), "-").concat(Math.random().toString(36).slice(2, 7)),
    // Autark's `roads` layer sizes each feature from `properties.highway`.
    // Missing this tag falls back to a city street width (3.5 m half-width),
    // making newly drawn sidewalk segments much heavier than the input paths.
    properties: {
      highway: 'path',
      source: 'curio-sidewalk-tile-edit',
      edit: 'draw_edge'
    },
    geometry: {
      type: 'LineString',
      coordinates: coordinates
    }
  };
  return _objectSpread(_objectSpread({}, fc), {}, {
    features: [].concat(_toConsumableArray(fc.features), [feature])
  });
}
function connectNetworkNodes(fc, a, b) {
  if (pointKey(a) === pointKey(b)) return fc;
  // Stewards' addDrawnEdge checks adjacency within every graph edge, including
  // polylines. A separate GeoJSON feature with the same segment is not an edit.
  var exists = fc.features.some(function (f) {
    return isLineFeature(f) && f.geometry.coordinates.some(function (p, index) {
      if (index === 0) return false;
      var previous = f.geometry.coordinates[index - 1];
      return pointKey(previous) === pointKey(a) && pointKey(p) === pointKey(b) || pointKey(previous) === pointKey(b) && pointKey(p) === pointKey(a);
    });
  });
  return exists ? fc : drawNetworkEdge(fc, [a, b]);
}
function splitNetworkEdge(fc, featureIndex, segmentIndex, at) {
  var _source$properties, _source$id, _source$id2, _source$id3, _source$id4;
  var source = fc.features[featureIndex];
  if (!source || !isLineFeature(source)) return fc;
  var coords = source.geometry.coordinates;
  if (segmentIndex < 0 || segmentIndex >= coords.length - 1) return fc;
  var left = [].concat(_toConsumableArray(coords.slice(0, segmentIndex + 1)), [at]);
  var right = [at].concat(_toConsumableArray(coords.slice(segmentIndex + 1)));
  var common = _objectSpread(_objectSpread({}, source), {}, {
    properties: _objectSpread({}, (_source$properties = source.properties) !== null && _source$properties !== void 0 ? _source$properties : {})
  });
  var first = _objectSpread(_objectSpread({}, common), {}, {
    id: "".concat(String((_source$id = source.id) !== null && _source$id !== void 0 ? _source$id : "feature-".concat(featureIndex)), ":a"),
    properties: _objectSpread(_objectSpread({}, common.properties), {}, {
      split_from: (_source$id2 = source.id) !== null && _source$id2 !== void 0 ? _source$id2 : featureIndex
    }),
    geometry: {
      type: 'LineString',
      coordinates: left
    }
  });
  var second = _objectSpread(_objectSpread({}, common), {}, {
    id: "".concat(String((_source$id3 = source.id) !== null && _source$id3 !== void 0 ? _source$id3 : "feature-".concat(featureIndex)), ":b"),
    properties: _objectSpread(_objectSpread({}, common.properties), {}, {
      split_from: (_source$id4 = source.id) !== null && _source$id4 !== void 0 ? _source$id4 : featureIndex
    }),
    geometry: {
      type: 'LineString',
      coordinates: right
    }
  });
  return _objectSpread(_objectSpread({}, fc), {}, {
    features: [].concat(_toConsumableArray(fc.features.slice(0, featureIndex)), [first, second], _toConsumableArray(fc.features.slice(featureIndex + 1)))
  });
}
function deleteNetworkNode(fc, node) {
  var features = fc.features.filter(function (feature) {
    if (!isLineFeature(feature)) return true;
    return !feature.geometry.coordinates.some(function (position) {
      return pointKey(position) === pointKey(node);
    });
  });
  return features.length === fc.features.length ? fc : _objectSpread(_objectSpread({}, fc), {}, {
    features: features
  });
}
function deleteNetworkNodesInBounds(fc, bounds) {
  var _bounds2 = _slicedToArray(bounds, 4),
    xmin = _bounds2[0],
    ymin = _bounds2[1],
    xmax = _bounds2[2],
    ymax = _bounds2[3];
  var removed = new Set();
  var _iterator3 = _createForOfIteratorHelper(fc.features),
    _step3;
  try {
    for (_iterator3.s(); !(_step3 = _iterator3.n()).done;) {
      var feature = _step3.value;
      if (!isLineFeature(feature)) continue;
      var _iterator4 = _createForOfIteratorHelper(feature.geometry.coordinates),
        _step4;
      try {
        for (_iterator4.s(); !(_step4 = _iterator4.n()).done;) {
          var position = _step4.value;
          if (position[0] >= xmin && position[0] <= xmax && position[1] >= ymin && position[1] <= ymax) removed.add(pointKey(position));
        }
      } catch (err) {
        _iterator4.e(err);
      } finally {
        _iterator4.f();
      }
    }
  } catch (err) {
    _iterator3.e(err);
  } finally {
    _iterator3.f();
  }
  var features = fc.features.filter(function (feature) {
    if (!isLineFeature(feature)) return true;
    var coords = feature.geometry.coordinates;
    return !coords.some(function (position) {
      return removed.has(pointKey(position));
    });
  });
  return features.length === fc.features.length ? fc : _objectSpread(_objectSpread({}, fc), {}, {
    features: features
  });
}

/** Stewards' graph indexes every coordinate, including intermediate vertices. */
function networkNodes(fc) {
  var seen = new Set();
  var result = [];
  var _iterator5 = _createForOfIteratorHelper(fc.features),
    _step5;
  try {
    for (_iterator5.s(); !(_step5 = _iterator5.n()).done;) {
      var feature = _step5.value;
      if (!isLineFeature(feature)) continue;
      var _iterator6 = _createForOfIteratorHelper(feature.geometry.coordinates),
        _step6;
      try {
        for (_iterator6.s(); !(_step6 = _iterator6.n()).done;) {
          var p = _step6.value;
          var key = pointKey(p);
          if (!seen.has(key)) {
            seen.add(key);
            result.push(p);
          }
        }
      } catch (err) {
        _iterator6.e(err);
      } finally {
        _iterator6.f();
      }
    }
  } catch (err) {
    _iterator5.e(err);
  } finally {
    _iterator5.f();
  }
  return result;
}
function endpointNodes(fc) {
  var seen = new Set();
  var result = [];
  var _iterator7 = _createForOfIteratorHelper(fc.features),
    _step7;
  try {
    for (_iterator7.s(); !(_step7 = _iterator7.n()).done;) {
      var feature = _step7.value;
      if (!isLineFeature(feature) || feature.geometry.coordinates.length < 2) continue;
      for (var _i2 = 0, _arr = [feature.geometry.coordinates[0], feature.geometry.coordinates.at(-1)]; _i2 < _arr.length; _i2++) {
        var p = _arr[_i2];
        var key = pointKey(p);
        if (!seen.has(key)) {
          seen.add(key);
          result.push(p);
        }
      }
    }
  } catch (err) {
    _iterator7.e(err);
  } finally {
    _iterator7.f();
  }
  return result;
}
function validateNetwork(fc, bounds) {
  var issues = [];
  var _iterator8 = _createForOfIteratorHelper(fc.features.entries()),
    _step8;
  try {
    for (_iterator8.s(); !(_step8 = _iterator8.n()).done;) {
      var _step8$value = _slicedToArray(_step8.value, 2),
        index = _step8$value[0],
        feature = _step8$value[1];
      if (!isLineFeature(feature)) {
        issues.push("Feature ".concat(index + 1, " is not a LineString."));
        continue;
      }
      if (feature.geometry.coordinates.length < 2) issues.push("Feature ".concat(index + 1, " has fewer than two points."));
      var _iterator9 = _createForOfIteratorHelper(feature.geometry.coordinates),
        _step9;
      try {
        for (_iterator9.s(); !(_step9 = _iterator9.n()).done;) {
          var p = _step9.value;
          if (!Number.isFinite(p[0]) || !Number.isFinite(p[1])) issues.push("Feature ".concat(index + 1, " contains an invalid coordinate."));
          if (p[0] < bounds[0] - 1e-9 || p[0] > bounds[2] + 1e-9 || p[1] < bounds[1] - 1e-9 || p[1] > bounds[3] + 1e-9) {
            issues.push("Feature ".concat(index + 1, " extends beyond this tile."));
            break;
          }
        }
      } catch (err) {
        _iterator9.e(err);
      } finally {
        _iterator9.f();
      }
    }
  } catch (err) {
    _iterator8.e(err);
  } finally {
    _iterator8.f();
  }
  return _toConsumableArray(new Set(issues));
}

/***/ },

/***/ "../../../packages/curio.sidewalk-stewards@1/sources/sidewalkNodeStyles.ts"
/*!*********************************************************************************!*\
  !*** ../../../packages/curio.sidewalk-stewards@1/sources/sidewalkNodeStyles.ts ***!
  \*********************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   sidewalkNodeStyles: () => (/* binding */ sidewalkNodeStyles)
/* harmony export */ });
/** Package-local presentation using the same tokens as Curio's built-in node bodies. */
var sidewalkNodeStyles = {
  body: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    minHeight: 0,
    boxSizing: 'border-box',
    gap: 6,
    padding: '6px 0',
    fontFamily: 'var(--curio-font-family)',
    fontSize: 'var(--curio-font-size-sm)',
    color: 'var(--curio-text-primary)',
    background: 'var(--curio-card-bg)'
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 6
  },
  field: {
    display: 'flex',
    flexDirection: 'column',
    gap: 3,
    fontSize: 'var(--curio-font-size-xs)',
    color: 'var(--curio-text-secondary)'
  },
  input: {
    boxSizing: 'border-box',
    minWidth: 0,
    minHeight: 28,
    padding: '3px 8px',
    fontFamily: 'inherit',
    fontSize: 'var(--curio-font-size-sm)',
    border: '1px solid var(--curio-border-strong)',
    borderRadius: 'var(--curio-radius-sm)',
    background: 'var(--curio-card-bg)',
    color: 'var(--curio-text-primary)'
  },
  button: {
    minHeight: 26,
    padding: '2px 10px',
    fontFamily: 'inherit',
    fontSize: 'var(--curio-font-size-xs)',
    lineHeight: '20px',
    border: '1px solid var(--curio-border-strong)',
    borderRadius: 'var(--curio-radius-pill)',
    background: 'var(--curio-card-bg)',
    color: 'var(--curio-text-primary)',
    cursor: 'pointer'
  },
  primaryButton: {
    minHeight: 26,
    padding: '2px 12px',
    fontFamily: 'inherit',
    fontSize: 'var(--curio-font-size-xs)',
    fontWeight: 600,
    lineHeight: '20px',
    border: '1px solid var(--curio-top-bar-bg)',
    borderRadius: 'var(--curio-radius-pill)',
    background: 'var(--curio-top-bar-bg)',
    color: 'var(--curio-text-on-dark)',
    cursor: 'pointer'
  },
  disabledButton: {
    background: 'var(--curio-surface-muted)',
    borderColor: 'var(--curio-border)',
    color: 'var(--curio-text-secondary)',
    cursor: 'default'
  },
  helper: {
    margin: 0,
    fontSize: 'var(--curio-font-size-xs)',
    color: 'var(--curio-text-secondary)'
  },
  panel: {
    border: '1px solid var(--curio-border)',
    borderRadius: 'var(--curio-radius-md)',
    background: 'var(--curio-surface-muted)',
    padding: '6px 8px'
  },
  status: {
    margin: 0,
    fontSize: 'var(--curio-font-size-xs)',
    color: 'var(--curio-text-secondary)'
  },
  warning: {
    margin: 0,
    padding: '5px 8px',
    maxHeight: 48,
    overflow: 'auto',
    fontSize: 'var(--curio-font-size-xs)',
    color: 'var(--curio-warning-text)',
    background: 'var(--curio-warning-bg)',
    borderRadius: 'var(--curio-radius-sm)'
  },
  error: {
    margin: 0,
    padding: '5px 8px',
    maxHeight: 48,
    overflow: 'auto',
    fontSize: 'var(--curio-font-size-xs)',
    color: 'var(--curio-danger-text)',
    background: 'var(--curio-danger-bg)',
    borderRadius: 'var(--curio-radius-sm)'
  }
};

/***/ },

/***/ "../../../packages/curio.sidewalk-stewards@1/sources/sidewalkPreparation.tsx"
/*!***********************************************************************************!*\
  !*** ../../../packages/curio.sidewalk-stewards@1/sources/sidewalkPreparation.tsx ***!
  \***********************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   usePreparedInput: () => (/* binding */ usePreparedInput),
/* harmony export */   useSidewalkPreparation: () => (/* binding */ useSidewalkPreparation)
/* harmony export */ });
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! react */ "react");
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(react__WEBPACK_IMPORTED_MODULE_0__);
/* harmony import */ var _beforeAfterContext__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! ./beforeAfterContext */ "../../../packages/curio.sidewalk-stewards@1/sources/beforeAfterContext.ts");
/* harmony import */ var _resourceResolver__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(/*! ./resourceResolver */ "../../../packages/curio.sidewalk-stewards@1/sources/resourceResolver.ts");
/* harmony import */ var _SidewalkTileEditor__WEBPACK_IMPORTED_MODULE_3__ = __webpack_require__(/*! ./SidewalkTileEditor */ "../../../packages/curio.sidewalk-stewards@1/sources/SidewalkTileEditor.tsx");
/* harmony import */ var _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_4__ = __webpack_require__(/*! ./sidewalkNodeStyles */ "../../../packages/curio.sidewalk-stewards@1/sources/sidewalkNodeStyles.ts");
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: !0, configurable: !0, writable: !0 }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == _typeof(i) ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != _typeof(t) || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r || "default"); if ("object" != _typeof(i)) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
function _regenerator() { /*! regenerator-runtime -- Copyright (c) 2014-present, Facebook, Inc. -- license (MIT): https://github.com/babel/babel/blob/main/packages/babel-helpers/LICENSE */ var e, t, r = "function" == typeof Symbol ? Symbol : {}, n = r.iterator || "@@iterator", o = r.toStringTag || "@@toStringTag"; function i(r, n, o, i) { var c = n && n.prototype instanceof Generator ? n : Generator, u = Object.create(c.prototype); return _regeneratorDefine2(u, "_invoke", function (r, n, o) { var i, c, u, f = 0, p = o || [], y = !1, G = { p: 0, n: 0, v: e, a: d, f: d.bind(e, 4), d: function d(t, r) { return i = t, c = 0, u = e, G.n = r, a; } }; function d(r, n) { for (c = r, u = n, t = 0; !y && f && !o && t < p.length; t++) { var o, i = p[t], d = G.p, l = i[2]; r > 3 ? (o = l === n) && (u = i[(c = i[4]) ? 5 : (c = 3, 3)], i[4] = i[5] = e) : i[0] <= d && ((o = r < 2 && d < i[1]) ? (c = 0, G.v = n, G.n = i[1]) : d < l && (o = r < 3 || i[0] > n || n > l) && (i[4] = r, i[5] = n, G.n = l, c = 0)); } if (o || r > 1) return a; throw y = !0, n; } return function (o, p, l) { if (f > 1) throw TypeError("Generator is already running"); for (y && 1 === p && d(p, l), c = p, u = l; (t = c < 2 ? e : u) || !y;) { i || (c ? c < 3 ? (c > 1 && (G.n = -1), d(c, u)) : G.n = u : G.v = u); try { if (f = 2, i) { if (c || (o = "next"), t = i[o]) { if (!(t = t.call(i, u))) throw TypeError("iterator result is not an object"); if (!t.done) return t; u = t.value, c < 2 && (c = 0); } else 1 === c && (t = i["return"]) && t.call(i), c < 2 && (u = TypeError("The iterator does not provide a '" + o + "' method"), c = 1); i = e; } else if ((t = (y = G.n < 0) ? u : r.call(n, G)) !== a) break; } catch (t) { i = e, c = 1, u = t; } finally { f = 1; } } return { value: t, done: y }; }; }(r, o, i), !0), u; } var a = {}; function Generator() {} function GeneratorFunction() {} function GeneratorFunctionPrototype() {} t = Object.getPrototypeOf; var c = [][n] ? t(t([][n]())) : (_regeneratorDefine2(t = {}, n, function () { return this; }), t), u = GeneratorFunctionPrototype.prototype = Generator.prototype = Object.create(c); function f(e) { return Object.setPrototypeOf ? Object.setPrototypeOf(e, GeneratorFunctionPrototype) : (e.__proto__ = GeneratorFunctionPrototype, _regeneratorDefine2(e, o, "GeneratorFunction")), e.prototype = Object.create(u), e; } return GeneratorFunction.prototype = GeneratorFunctionPrototype, _regeneratorDefine2(u, "constructor", GeneratorFunctionPrototype), _regeneratorDefine2(GeneratorFunctionPrototype, "constructor", GeneratorFunction), GeneratorFunction.displayName = "GeneratorFunction", _regeneratorDefine2(GeneratorFunctionPrototype, o, "GeneratorFunction"), _regeneratorDefine2(u), _regeneratorDefine2(u, o, "Generator"), _regeneratorDefine2(u, n, function () { return this; }), _regeneratorDefine2(u, "toString", function () { return "[object Generator]"; }), (_regenerator = function _regenerator() { return { w: i, m: f }; })(); }
function _regeneratorDefine2(e, r, n, t) { var i = Object.defineProperty; try { i({}, "", {}); } catch (e) { i = 0; } _regeneratorDefine2 = function _regeneratorDefine(e, r, n, t) { function o(r, n) { _regeneratorDefine2(e, r, function (e) { return this._invoke(r, n, e); }); } r ? i ? i(e, r, { value: n, enumerable: !t, configurable: !t, writable: !t }) : e[r] = n : (o("next", 0), o("throw", 1), o("return", 2)); }, _regeneratorDefine2(e, r, n, t); }
function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
function asyncGeneratorStep(n, t, e, r, o, a, c) { try { var i = n[a](c), u = i.value; } catch (n) { return void e(n); } i.done ? t(u) : Promise.resolve(u).then(r, o); }
function _asyncToGenerator(n) { return function () { var t = this, e = arguments; return new Promise(function (r, o) { var a = n.apply(t, e); function _next(n) { asyncGeneratorStep(a, r, o, _next, _throw, "next", n); } function _throw(n) { asyncGeneratorStep(a, r, o, _next, _throw, "throw", n); } _next(void 0); }); }; }
function _slicedToArray(r, e) { return _arrayWithHoles(r) || _iterableToArrayLimit(r, e) || _unsupportedIterableToArray(r, e) || _nonIterableRest(); }
function _nonIterableRest() { throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
function _iterableToArrayLimit(r, l) { var t = null == r ? null : "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (null != t) { var e, n, i, u, a = [], f = !0, o = !1; try { if (i = (t = t.call(r)).next, 0 === l) { if (Object(t) !== t) return; f = !1; } else for (; !(f = (e = i.call(t)).done) && (a.push(e.value), a.length !== l); f = !0); } catch (r) { o = !0, n = r; } finally { try { if (!f && null != t["return"] && (u = t["return"](), Object(u) !== u)) return; } finally { if (o) throw n; } } return a; } }
function _arrayWithHoles(r) { if (Array.isArray(r)) return r; }





function usePreparedInput(input) {
  var enabled = arguments.length > 1 && arguments[1] !== undefined ? arguments[1] : true;
  var _React$useState = react__WEBPACK_IMPORTED_MODULE_0___default().useState(null),
    _React$useState2 = _slicedToArray(_React$useState, 2),
    loaded = _React$useState2[0],
    setLoaded = _React$useState2[1];
  var _React$useState3 = react__WEBPACK_IMPORTED_MODULE_0___default().useState(''),
    _React$useState4 = _slicedToArray(_React$useState3, 2),
    error = _React$useState4[0],
    setError = _React$useState4[1];
  react__WEBPACK_IMPORTED_MODULE_0___default().useEffect(function () {
    setLoaded(null);
    setError('');
    if (!enabled) return;
    var controller = new AbortController();
    (0,_beforeAfterContext__WEBPACK_IMPORTED_MODULE_1__.readPreparedContext)(input, controller.signal).then(function (context) {
      if (!controller.signal.aborted) setLoaded({
        input: input,
        context: context
      });
    })["catch"](function (e) {
      if (!controller.signal.aborted) setError(e.message);
    });
    return function () {
      return controller.abort();
    };
  }, [input, enabled]);
  return {
    context: loaded && loaded.input === input ? loaded.context : null,
    error: error
  };
}
/** Async preparation participates in Run All through the existing package play override. */
function useSidewalkPreparation(data, state) {
  var _React$useState5 = react__WEBPACK_IMPORTED_MODULE_0___default().useState('Connect satellite and network Data Loading inputs.'),
    _React$useState6 = _slicedToArray(_React$useState5, 2),
    message = _React$useState6[0],
    setMessage = _React$useState6[1];
  var refs = react__WEBPACK_IMPORTED_MODULE_0___default().useRef({
    data: data,
    state: state
  });
  refs.current = {
    data: data,
    state: state
  };
  var pending = react__WEBPACK_IMPORTED_MODULE_0___default().useRef(null);
  var published = react__WEBPACK_IMPORTED_MODULE_0___default().useRef('');
  var getContext = function getContext() {
    var input = refs.current.data.input;
    if (!pending.current || pending.current.input !== input) {
      var _pending$current;
      (_pending$current = pending.current) === null || _pending$current === void 0 || _pending$current.controller.abort();
      var controller = new AbortController();
      pending.current = {
        input: input,
        controller: controller,
        promise: (0,_beforeAfterContext__WEBPACK_IMPORTED_MODULE_1__.prepareContext)(input, undefined, undefined, controller.signal)
      };
    }
    return pending.current;
  };
  var run = /*#__PURE__*/function () {
    var _ref = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee() {
      var force,
        request,
        base,
        raw,
        options,
        context,
        response,
        publication,
        _message,
        _args = arguments,
        _t,
        _t2,
        _t3;
      return _regenerator().w(function (_context) {
        while (1) switch (_context.p = _context.n) {
          case 0:
            force = _args.length > 0 && _args[0] !== undefined ? _args[0] : false;
            request = getContext();
            _context.p = 1;
            _context.n = 2;
            return request.promise;
          case 2:
            base = _context.v;
            if (!request.controller.signal.aborted) {
              _context.n = 3;
              break;
            }
            return _context.a(2);
          case 3:
            raw = refs.current.state.code.trim();
            options = raw ? JSON.parse(raw) : {};
            if (!(!options || _typeof(options) !== 'object' || Array.isArray(options))) {
              _context.n = 4;
              break;
            }
            throw new Error('Sidewalk Prepare configuration must be a JSON object.');
          case 4:
            context = base;
            if (!options.measuredTileGridUrl) {
              _context.n = 9;
              break;
            }
            if (!(typeof options.measuredTileGridUrl !== 'string' || !Array.isArray(options.measurementFields))) {
              _context.n = 5;
              break;
            }
            throw new Error('Measured tile grid needs a URL and measurementFields array.');
          case 5:
            _context.n = 6;
            return fetch((0,_resourceResolver__WEBPACK_IMPORTED_MODULE_2__.assetUrl)(options.measuredTileGridUrl), {
              signal: request.controller.signal
            });
          case 6:
            response = _context.v;
            if (response.ok) {
              _context.n = 7;
              break;
            }
            throw new Error("Measured tile grid failed (HTTP ".concat(response.status, ")."));
          case 7:
            _t = _beforeAfterContext__WEBPACK_IMPORTED_MODULE_1__.withTileMeasurements;
            _t2 = base;
            _context.n = 8;
            return response.json();
          case 8:
            context = _t(_t2, _context.v, options.measurementFields);
          case 9:
            publication = "".concat(context.sourceIdentity, ":").concat(raw);
            if (force || published.current !== publication) {
              refs.current.data.outputCallback(data.nodeId, (0,_beforeAfterContext__WEBPACK_IMPORTED_MODULE_1__.contextOutput)(context, (0,_SidewalkTileEditor__WEBPACK_IMPORTED_MODULE_3__.parseSidewalkEditConfig)('')));
              published.current = publication;
            }
            refs.current.state.setOutput({
              code: 'success',
              content: 'Prepared both source inputs; Before is independent of the editor.'
            });
            setMessage("Prepared ".concat(context.grid.features.length, " tiles and ").concat(context.network.features.length, " original network features."));
            _context.n = 12;
            break;
          case 10:
            _context.p = 10;
            _t3 = _context.v;
            if (!request.controller.signal.aborted) {
              _context.n = 11;
              break;
            }
            return _context.a(2);
          case 11:
            _message = _t3 instanceof Error ? _t3.message : String(_t3);
            if (published.current) {
              refs.current.data.outputCallback(data.nodeId, null);
              published.current = '';
            }
            refs.current.state.setOutput({
              code: 'error',
              content: _message
            });
            setMessage(_message);
          case 12:
            return _context.a(2);
        }
      }, _callee, null, [[1, 10]]);
    }));
    return function run() {
      return _ref.apply(this, arguments);
    };
  }();
  react__WEBPACK_IMPORTED_MODULE_0___default().useEffect(function () {
    void run();
  }, [data.input, state.code]);
  react__WEBPACK_IMPORTED_MODULE_0___default().useEffect(function () {
    return function () {
      var _pending$current2;
      return (_pending$current2 = pending.current) === null || _pending$current2 === void 0 ? void 0 : _pending$current2.controller.abort();
    };
  }, []);
  return {
    disablePlay: false,
    sendCodeOverride: function () {
      var _sendCodeOverride = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee2() {
        return _regenerator().w(function (_context2) {
          while (1) switch (_context2.n) {
            case 0:
              return _context2.a(2, run(true));
          }
        }, _callee2);
      }));
      function sendCodeOverride() {
        return _sendCodeOverride.apply(this, arguments);
      }
      return sendCodeOverride;
    }(),
    contentComponent: /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      className: "nodrag nopan nowheel",
      style: _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_4__.sidewalkNodeStyles.body
    }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      role: "status",
      style: _objectSpread(_objectSpread({}, _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_4__.sidewalkNodeStyles.panel), {}, {
        fontSize: 'var(--curio-font-size-xs)'
      })
    }, message))
  };
}

/***/ },

/***/ "../../../packages/curio.sidewalk-stewards@1/sources/sidewalkTileEditBehavior.tsx"
/*!****************************************************************************************!*\
  !*** ../../../packages/curio.sidewalk-stewards@1/sources/sidewalkTileEditBehavior.tsx ***!
  \****************************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   useSidewalkTileEditBehavior: () => (/* binding */ useSidewalkTileEditBehavior)
/* harmony export */ });
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! react */ "react");
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(react__WEBPACK_IMPORTED_MODULE_0__);
/* harmony import */ var _SidewalkTileEditor__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! ./SidewalkTileEditor */ "../../../packages/curio.sidewalk-stewards@1/sources/SidewalkTileEditor.tsx");
/* harmony import */ var _autkSelection__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(/*! ./autkSelection */ "../../../packages/curio.sidewalk-stewards@1/sources/autkSelection.ts");
/* harmony import */ var _sidewalkPreparation__WEBPACK_IMPORTED_MODULE_3__ = __webpack_require__(/*! ./sidewalkPreparation */ "../../../packages/curio.sidewalk-stewards@1/sources/sidewalkPreparation.tsx");
/* harmony import */ var _beforeAfterContext__WEBPACK_IMPORTED_MODULE_4__ = __webpack_require__(/*! ./beforeAfterContext */ "../../../packages/curio.sidewalk-stewards@1/sources/beforeAfterContext.ts");
/* harmony import */ var _useSidewalkOverview__WEBPACK_IMPORTED_MODULE_5__ = __webpack_require__(/*! ./useSidewalkOverview */ "../../../packages/curio.sidewalk-stewards@1/sources/useSidewalkOverview.ts");
/* harmony import */ var _streetViewContract__WEBPACK_IMPORTED_MODULE_6__ = __webpack_require__(/*! ./streetViewContract */ "../../../packages/curio.sidewalk-stewards@1/sources/streetViewContract.ts");
/* harmony import */ var _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_7__ = __webpack_require__(/*! ./sidewalkNodeStyles */ "../../../packages/curio.sidewalk-stewards@1/sources/sidewalkNodeStyles.ts");
/* harmony import */ var _tileNeighbors__WEBPACK_IMPORTED_MODULE_8__ = __webpack_require__(/*! ./tileNeighbors */ "../../../packages/curio.sidewalk-stewards@1/sources/tileNeighbors.ts");
function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
function _regenerator() { /*! regenerator-runtime -- Copyright (c) 2014-present, Facebook, Inc. -- license (MIT): https://github.com/babel/babel/blob/main/packages/babel-helpers/LICENSE */ var e, t, r = "function" == typeof Symbol ? Symbol : {}, n = r.iterator || "@@iterator", o = r.toStringTag || "@@toStringTag"; function i(r, n, o, i) { var c = n && n.prototype instanceof Generator ? n : Generator, u = Object.create(c.prototype); return _regeneratorDefine2(u, "_invoke", function (r, n, o) { var i, c, u, f = 0, p = o || [], y = !1, G = { p: 0, n: 0, v: e, a: d, f: d.bind(e, 4), d: function d(t, r) { return i = t, c = 0, u = e, G.n = r, a; } }; function d(r, n) { for (c = r, u = n, t = 0; !y && f && !o && t < p.length; t++) { var o, i = p[t], d = G.p, l = i[2]; r > 3 ? (o = l === n) && (u = i[(c = i[4]) ? 5 : (c = 3, 3)], i[4] = i[5] = e) : i[0] <= d && ((o = r < 2 && d < i[1]) ? (c = 0, G.v = n, G.n = i[1]) : d < l && (o = r < 3 || i[0] > n || n > l) && (i[4] = r, i[5] = n, G.n = l, c = 0)); } if (o || r > 1) return a; throw y = !0, n; } return function (o, p, l) { if (f > 1) throw TypeError("Generator is already running"); for (y && 1 === p && d(p, l), c = p, u = l; (t = c < 2 ? e : u) || !y;) { i || (c ? c < 3 ? (c > 1 && (G.n = -1), d(c, u)) : G.n = u : G.v = u); try { if (f = 2, i) { if (c || (o = "next"), t = i[o]) { if (!(t = t.call(i, u))) throw TypeError("iterator result is not an object"); if (!t.done) return t; u = t.value, c < 2 && (c = 0); } else 1 === c && (t = i["return"]) && t.call(i), c < 2 && (u = TypeError("The iterator does not provide a '" + o + "' method"), c = 1); i = e; } else if ((t = (y = G.n < 0) ? u : r.call(n, G)) !== a) break; } catch (t) { i = e, c = 1, u = t; } finally { f = 1; } } return { value: t, done: y }; }; }(r, o, i), !0), u; } var a = {}; function Generator() {} function GeneratorFunction() {} function GeneratorFunctionPrototype() {} t = Object.getPrototypeOf; var c = [][n] ? t(t([][n]())) : (_regeneratorDefine2(t = {}, n, function () { return this; }), t), u = GeneratorFunctionPrototype.prototype = Generator.prototype = Object.create(c); function f(e) { return Object.setPrototypeOf ? Object.setPrototypeOf(e, GeneratorFunctionPrototype) : (e.__proto__ = GeneratorFunctionPrototype, _regeneratorDefine2(e, o, "GeneratorFunction")), e.prototype = Object.create(u), e; } return GeneratorFunction.prototype = GeneratorFunctionPrototype, _regeneratorDefine2(u, "constructor", GeneratorFunctionPrototype), _regeneratorDefine2(GeneratorFunctionPrototype, "constructor", GeneratorFunction), GeneratorFunction.displayName = "GeneratorFunction", _regeneratorDefine2(GeneratorFunctionPrototype, o, "GeneratorFunction"), _regeneratorDefine2(u), _regeneratorDefine2(u, o, "Generator"), _regeneratorDefine2(u, n, function () { return this; }), _regeneratorDefine2(u, "toString", function () { return "[object Generator]"; }), (_regenerator = function _regenerator() { return { w: i, m: f }; })(); }
function _regeneratorDefine2(e, r, n, t) { var i = Object.defineProperty; try { i({}, "", {}); } catch (e) { i = 0; } _regeneratorDefine2 = function _regeneratorDefine(e, r, n, t) { function o(r, n) { _regeneratorDefine2(e, r, function (e) { return this._invoke(r, n, e); }); } r ? i ? i(e, r, { value: n, enumerable: !t, configurable: !t, writable: !t }) : e[r] = n : (o("next", 0), o("throw", 1), o("return", 2)); }, _regeneratorDefine2(e, r, n, t); }
function asyncGeneratorStep(n, t, e, r, o, a, c) { try { var i = n[a](c), u = i.value; } catch (n) { return void e(n); } i.done ? t(u) : Promise.resolve(u).then(r, o); }
function _asyncToGenerator(n) { return function () { var t = this, e = arguments; return new Promise(function (r, o) { var a = n.apply(t, e); function _next(n) { asyncGeneratorStep(a, r, o, _next, _throw, "next", n); } function _throw(n) { asyncGeneratorStep(a, r, o, _next, _throw, "throw", n); } _next(void 0); }); }; }
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: !0, configurable: !0, writable: !0 }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == _typeof(i) ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != _typeof(t) || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r || "default"); if ("object" != _typeof(i)) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
function _slicedToArray(r, e) { return _arrayWithHoles(r) || _iterableToArrayLimit(r, e) || _unsupportedIterableToArray(r, e) || _nonIterableRest(); }
function _nonIterableRest() { throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
function _iterableToArrayLimit(r, l) { var t = null == r ? null : "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (null != t) { var e, n, i, u, a = [], f = !0, o = !1; try { if (i = (t = t.call(r)).next, 0 === l) { if (Object(t) !== t) return; f = !1; } else for (; !(f = (e = i.call(t)).done) && (a.push(e.value), a.length !== l); f = !0); } catch (r) { o = !0, n = r; } finally { try { if (!f && null != t["return"] && (u = t["return"](), Object(u) !== u)) return; } finally { if (o) throw n; } } return a; } }
function _arrayWithHoles(r) { if (Array.isArray(r)) return r; }










/** Dedicated review/edit behavior for one selected prepared Stewards tile. */
function useSidewalkTileEditBehavior(data, nodeState) {
  var _config$overview, _prepared$context, _overview$context, _config$activeSelecti, _prepared$context$gri, _prepared$context2, _overview$context$gri, _overview$context2, _prepared$context3;
  // Keep the active edit tile independently of analytical brush candidates.
  var activeTile = react__WEBPACK_IMPORTED_MODULE_0___default().useRef({
    seen: false,
    index: null,
    featureId: null,
    feature: null,
    sourceFingerprint: '',
    viaNavigation: false
  });
  var lastMapPick = react__WEBPACK_IMPORTED_MODULE_0___default().useRef(null);
  var _React$useState = react__WEBPACK_IMPORTED_MODULE_0___default().useState(0),
    _React$useState2 = _slicedToArray(_React$useState, 2),
    refreshNavigation = _React$useState2[1];
  var _React$useState3 = react__WEBPACK_IMPORTED_MODULE_0___default().useState(null),
    _React$useState4 = _slicedToArray(_React$useState3, 2),
    legacyChoice = _React$useState4[0],
    setLegacyChoice = _React$useState4[1];
  var persistedConfig = (0,_SidewalkTileEditor__WEBPACK_IMPORTED_MODULE_1__.parseSidewalkEditConfig)(nodeState.code);
  var inputMode = persistedConfig.mode === 'input-overview';
  var prepared = (0,_sidewalkPreparation__WEBPACK_IMPORTED_MODULE_3__.usePreparedInput)(data.input, inputMode);
  var config = prepared.context ? (0,_beforeAfterContext__WEBPACK_IMPORTED_MODULE_4__.contextConfig)(prepared.context, persistedConfig) : inputMode ? _objectSpread(_objectSpread({}, persistedConfig), {}, {
    overview: undefined
  }) : persistedConfig;
  var fingerprint = (0,_streetViewContract__WEBPACK_IMPORTED_MODULE_6__.sourceFingerprint)((_config$overview = config.overview) === null || _config$overview === void 0 ? void 0 : _config$overview.sourceIdentity, config.imageUrlTemplate, config.networkUrlTemplate, data.input);
  var emit = function emit(output) {
    return data.outputCallback(data.nodeId, output);
  };
  var overview = (0,_useSidewalkOverview__WEBPACK_IMPORTED_MODULE_5__.useSidewalkOverview)(config, emit, inputMode ? prepared.context : undefined);
  var grid = inputMode ? (_prepared$context = prepared.context) === null || _prepared$context === void 0 ? void 0 : _prepared$context.grid : config.overview ? (_overview$context = overview.context) === null || _overview$context === void 0 ? void 0 : _overview$context.grid : data.input;
  var neighborIndex = react__WEBPACK_IMPORTED_MODULE_0___default().useMemo(function () {
    return (grid === null || grid === void 0 ? void 0 : grid.type) === 'FeatureCollection' && Array.isArray(grid.features) ? (0,_tileNeighbors__WEBPACK_IMPORTED_MODULE_8__.buildTileNeighborIndex)(grid) : null;
  }, [grid, fingerprint]);
  // Curio delivers the most recent *source* over a mutual edge. A camera
  // event can therefore replace the incoming Autark payload without clearing
  // the editor's selection. Only another Autark selection may supersede it.
  var incomingSelection = (0,_autkSelection__WEBPACK_IMPORTED_MODULE_2__.latestAutkSelection)(data.interactions);
  var rememberedSelection = react__WEBPACK_IMPORTED_MODULE_0___default().useRef(incomingSelection);
  if (incomingSelection) rememberedSelection.current = incomingSelection;
  var picked = incomingSelection !== null && incomingSelection !== void 0 ? incomingSelection : rememberedSelection.current;
  react__WEBPACK_IMPORTED_MODULE_0___default().useEffect(function () {
    if (legacyChoice !== null && ((picked === null || picked === void 0 ? void 0 : picked.kind) !== 'legacy' || !picked.indices.includes(legacyChoice))) {
      setLegacyChoice(null);
    }
  }, [picked, legacyChoice]);
  if ((picked === null || picked === void 0 ? void 0 : picked.kind) === 'map-pick' && picked.event !== lastMapPick.current) {
    lastMapPick.current = picked.event;
    activeTile.current = {
      seen: true,
      index: picked.activeIndex,
      featureId: picked.activeIndex === null ? null : picked.featureId,
      feature: picked.activeIndex === null ? null : picked.feature,
      sourceFingerprint: fingerprint,
      viaNavigation: false
    };
  }
  var activeForSource = activeTile.current.sourceFingerprint === fingerprint ? activeTile.current : null;
  var legacy = (picked === null || picked === void 0 ? void 0 : picked.kind) === 'legacy';
  var selectionIndex = legacy ? legacyChoice !== null && picked.indices.includes(legacyChoice) ? legacyChoice : null : activeForSource !== null && activeForSource !== void 0 && activeForSource.seen ? activeForSource.index : null;
  var selectionFeatureId = legacy ? null : activeForSource !== null && activeForSource !== void 0 && activeForSource.seen ? activeForSource.featureId : ((_config$activeSelecti = config.activeSelection) === null || _config$activeSelecti === void 0 ? void 0 : _config$activeSelecti.sourceFingerprint) === fingerprint ? config.activeSelection.tileId : null;
  var selectionFeature = legacy ? null : activeForSource === null || activeForSource === void 0 ? void 0 : activeForSource.feature;
  var persist = function persist(next) {
    // Curio persists node.data.code with the workflow. Store corrections and
    // their undo/redo journal here so drafts survive closing and reopening.
    nodeState.setCode(JSON.stringify(next));
  };
  var interactionsCallback = function interactionsCallback(interactions, nodeId) {
    return data.interactionsCallback(interactions, nodeId);
  };
  var navigateToTile = function navigateToTile(tileId) {
    var _picked$layerRef;
    var feature = neighborIndex === null || neighborIndex === void 0 ? void 0 : neighborIndex.features.get(tileId);
    var index = neighborIndex === null || neighborIndex === void 0 ? void 0 : neighborIndex.positions.get(tileId);
    if (!feature || index === undefined) return;
    activeTile.current = {
      seen: true,
      index: index,
      featureId: tileId,
      feature: feature,
      sourceFingerprint: fingerprint,
      viaNavigation: true
    };
    refreshNavigation(function (revision) {
      return revision + 1;
    });
    // The prepared context publishes this complete grid as the upstream layer.
    // This highlights one editor tile through the existing mutual edge; the
    // PCP's own brushed candidate state is neither cleared nor rewritten.
    interactionsCallback({
      autk_selection: {
        type: 'POINT',
        data: [{
          tile_id: tileId
        }],
        priority: 1,
        source: 'SIDEWALK_TILE_EDIT',
        layerRef: (_picked$layerRef = picked === null || picked === void 0 ? void 0 : picked.layerRef) !== null && _picked$layerRef !== void 0 ? _picked$layerRef : 'upstream',
        selectionOrigin: {
          version: 1,
          kind: 'map-pick',
          activeIndex: index
        },
        featureId: tileId,
        feature: feature
      }
    }, data.nodeId);
  };
  var setStatus = function setStatus(status) {
    return nodeState.setOutput(status);
  };
  var contentComponent = /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement((react__WEBPACK_IMPORTED_MODULE_0___default().Fragment), null, inputMode && !prepared.context && !prepared.error && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    role: "status",
    style: _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_7__.sidewalkNodeStyles.panel
  }, "Loading prepared input context\u2026"), inputMode && prepared.error && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    role: "alert",
    style: _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_7__.sidewalkNodeStyles.error
  }, prepared.error), config.overview && overview.loading && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    role: "status",
    style: _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_7__.sidewalkNodeStyles.panel
  }, "Loading complete overview context\u2026"), config.overview && overview.error && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    role: "alert",
    style: _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_7__.sidewalkNodeStyles.error
  }, overview.error), legacy && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("label", {
    style: _objectSpread(_objectSpread({}, _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_7__.sidewalkNodeStyles.field), {}, {
      padding: '6px 0'
    })
  }, "Legacy selection: choose the active tile", /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("select", {
    "aria-label": "Active tile from legacy selection",
    value: selectionIndex !== null && selectionIndex !== void 0 ? selectionIndex : '',
    style: _sidewalkNodeStyles__WEBPACK_IMPORTED_MODULE_7__.sidewalkNodeStyles.input,
    onChange: function onChange(event) {
      return setLegacyChoice(event.target.value === '' ? null : Number(event.target.value));
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("option", {
    value: ""
  }, "Choose a tile"), picked.indices.map(function (index) {
    return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("option", {
      key: index,
      value: index
    }, "Selected row ", index + 1);
  }))), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement(_SidewalkTileEditor__WEBPACK_IMPORTED_MODULE_1__.SidewalkTileEditor, {
    nodeId: data.nodeId,
    input: inputMode ? (_prepared$context$gri = (_prepared$context2 = prepared.context) === null || _prepared$context2 === void 0 ? void 0 : _prepared$context2.grid) !== null && _prepared$context$gri !== void 0 ? _prepared$context$gri : null : config.overview ? (_overview$context$gri = (_overview$context2 = overview.context) === null || _overview$context2 === void 0 ? void 0 : _overview$context2.grid) !== null && _overview$context$gri !== void 0 ? _overview$context$gri : null : data.input,
    originalNetwork: inputMode ? (_prepared$context3 = prepared.context) === null || _prepared$context3 === void 0 ? void 0 : _prepared$context3.network : undefined,
    selectionIndex: selectionIndex,
    allowSingleTile: !picked,
    selectionFeatureId: selectionFeatureId,
    selectionFeature: activeForSource !== null && activeForSource !== void 0 && activeForSource.viaNavigation || !inputMode ? selectionFeature : null,
    neighborIndex: neighborIndex,
    onNavigate: navigateToTile,
    sourceFingerprint: fingerprint,
    incomingInteractions: data.interactions,
    config: config,
    persist: persist,
    emit: emit,
    onCommitted: config.overview ? overview.publish : undefined,
    interactionsCallback: interactionsCallback,
    setStatus: setStatus
  }));
  return _objectSpread({
    contentComponent: contentComponent,
    disablePlay: !inputMode
  }, inputMode ? {
    sendCodeOverride: function () {
      var _sendCodeOverride = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee() {
        var current, _t;
        return _regenerator().w(function (_context) {
          while (1) switch (_context.p = _context.n) {
            case 0:
              _context.p = 0;
              _context.n = 1;
              return (0,_beforeAfterContext__WEBPACK_IMPORTED_MODULE_4__.readPreparedContext)(data.input);
            case 1:
              current = _context.v;
              emit((0,_beforeAfterContext__WEBPACK_IMPORTED_MODULE_4__.contextOutput)(current, (0,_SidewalkTileEditor__WEBPACK_IMPORTED_MODULE_1__.parseSidewalkEditConfig)(nodeState.code)));
              setStatus({
                code: 'success',
                content: 'Published the complete confirmed network from prepared input.'
              });
              _context.n = 3;
              break;
            case 2:
              _context.p = 2;
              _t = _context.v;
              setStatus({
                code: 'error',
                content: _t instanceof Error ? _t.message : String(_t)
              });
            case 3:
              return _context.a(2);
          }
        }, _callee, null, [[0, 2]]);
      }));
      function sendCodeOverride() {
        return _sendCodeOverride.apply(this, arguments);
      }
      return sendCodeOverride;
    }()
  } : {});
}

/***/ },

/***/ "../../../packages/curio.sidewalk-stewards@1/sources/sidewalkTopology.ts"
/*!*******************************************************************************!*\
  !*** ../../../packages/curio.sidewalk-stewards@1/sources/sidewalkTopology.ts ***!
  \*******************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   validateSidewalkTopology: () => (/* binding */ validateSidewalkTopology)
/* harmony export */ });
function _slicedToArray(r, e) { return _arrayWithHoles(r) || _iterableToArrayLimit(r, e) || _unsupportedIterableToArray(r, e) || _nonIterableRest(); }
function _nonIterableRest() { throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _iterableToArrayLimit(r, l) { var t = null == r ? null : "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (null != t) { var e, n, i, u, a = [], f = !0, o = !1; try { if (i = (t = t.call(r)).next, 0 === l) { if (Object(t) !== t) return; f = !1; } else for (; !(f = (e = i.call(t)).done) && (a.push(e.value), a.length !== l); f = !0); } catch (r) { o = !0, n = r; } finally { try { if (!f && null != t["return"] && (u = t["return"](), Object(u) !== u)) return; } finally { if (o) throw n; } } return a; } }
function _arrayWithHoles(r) { if (Array.isArray(r)) return r; }
function _toConsumableArray(r) { return _arrayWithoutHoles(r) || _iterableToArray(r) || _unsupportedIterableToArray(r) || _nonIterableSpread(); }
function _nonIterableSpread() { throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _iterableToArray(r) { if ("undefined" != typeof Symbol && null != r[Symbol.iterator] || null != r["@@iterator"]) return Array.from(r); }
function _arrayWithoutHoles(r) { if (Array.isArray(r)) return _arrayLikeToArray(r); }
function _createForOfIteratorHelper(r, e) { var t = "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (!t) { if (Array.isArray(r) || (t = _unsupportedIterableToArray(r)) || e && r && "number" == typeof r.length) { t && (r = t); var _n = 0, F = function F() {}; return { s: F, n: function n() { return _n >= r.length ? { done: !0 } : { done: !1, value: r[_n++] }; }, e: function e(r) { throw r; }, f: F }; } throw new TypeError("Invalid attempt to iterate non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); } var o, a = !0, u = !1; return { s: function s() { t = t.call(r); }, n: function n() { var r = t.next(); return a = r.done, r; }, e: function e(r) { u = !0, o = r; }, f: function f() { try { a || null == t["return"] || t["return"](); } finally { if (u) throw o; } } }; }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
var coordinateKey = function coordinateKey(point) {
  return "".concat(Math.round(point[0] * 1e8), ",").concat(Math.round(point[1] * 1e8));
};
function endpointOnTileBoundary(point, bounds) {
  var tolerance = Math.max(bounds[2] - bounds[0], bounds[3] - bounds[1], 1) * 1e-7;
  return Math.abs(point[0] - bounds[0]) <= tolerance || Math.abs(point[0] - bounds[2]) <= tolerance || Math.abs(point[1] - bounds[1]) <= tolerance || Math.abs(point[1] - bounds[3]) <= tolerance;
}

/** Sidewalk-specific diagnostics. These are advisory until domain rules are approved. */
function validateSidewalkTopology(collection, bounds) {
  var endpointFeatures = new Map();
  var duplicateSegments = new Map();
  collection.features.forEach(function (feature, featureIndex) {
    var geometry = feature.geometry;
    if (!geometry || geometry.type !== 'LineString' || geometry.coordinates.length < 2) return;
    var coordinates = geometry.coordinates;
    for (var _i = 0, _arr = [coordinates[0], coordinates[coordinates.length - 1]]; _i < _arr.length; _i++) {
      var _endpointFeatures$get;
      var endpoint = _arr[_i];
      var key = coordinateKey(endpoint);
      var indexes = (_endpointFeatures$get = endpointFeatures.get(key)) !== null && _endpointFeatures$get !== void 0 ? _endpointFeatures$get : new Set();
      indexes.add(featureIndex);
      endpointFeatures.set(key, indexes);
    }
    for (var index = 1; index < coordinates.length; index += 1) {
      var _duplicateSegments$ge;
      var a = coordinateKey(coordinates[index - 1]);
      var b = coordinateKey(coordinates[index]);
      var _key = a < b ? "".concat(a, "|").concat(b) : "".concat(b, "|").concat(a);
      var _indexes = (_duplicateSegments$ge = duplicateSegments.get(_key)) !== null && _duplicateSegments$ge !== void 0 ? _duplicateSegments$ge : new Set();
      _indexes.add(featureIndex);
      duplicateSegments.set(_key, _indexes);
    }
  });
  var warnings = [];
  var danglingIndexes = new Set();
  var _iterator = _createForOfIteratorHelper(endpointFeatures),
    _step;
  try {
    for (_iterator.s(); !(_step = _iterator.n()).done;) {
      var _step$value = _slicedToArray(_step.value, 2),
        key = _step$value[0],
        indexes = _step$value[1];
      if (indexes.size !== 1) continue;
      var _key$split$map = key.split(',').map(function (value) {
          return Number(value) / 1e8;
        }),
        _key$split$map2 = _slicedToArray(_key$split$map, 2),
        x = _key$split$map2[0],
        y = _key$split$map2[1];
      if (endpointOnTileBoundary([x, y], bounds)) continue;
      indexes.forEach(function (index) {
        return danglingIndexes.add(index);
      });
    }
  } catch (err) {
    _iterator.e(err);
  } finally {
    _iterator.f();
  }
  if (danglingIndexes.size > 0) {
    warnings.push({
      code: 'dangling_endpoint',
      message: "".concat(danglingIndexes.size, " network feature(s) have endpoints that do not connect to another feature or reach the tile edge."),
      featureIndexes: _toConsumableArray(danglingIndexes).sort(function (a, b) {
        return a - b;
      })
    });
  }
  var duplicateIndexes = new Set();
  var _iterator2 = _createForOfIteratorHelper(duplicateSegments.values()),
    _step2;
  try {
    for (_iterator2.s(); !(_step2 = _iterator2.n()).done;) {
      var _indexes2 = _step2.value;
      if (_indexes2.size > 1) _indexes2.forEach(function (index) {
        return duplicateIndexes.add(index);
      });
    }
  } catch (err) {
    _iterator2.e(err);
  } finally {
    _iterator2.f();
  }
  if (duplicateIndexes.size > 0) {
    warnings.push({
      code: 'duplicate_segment',
      message: "Overlapping network segments appear in ".concat(duplicateIndexes.size, " feature(s)."),
      featureIndexes: _toConsumableArray(duplicateIndexes).sort(function (a, b) {
        return a - b;
      })
    });
  }
  return warnings;
}

/***/ },

/***/ "../../../packages/curio.sidewalk-stewards@1/sources/streetViewContract.ts"
/*!*********************************************************************************!*\
  !*** ../../../packages/curio.sidewalk-stewards@1/sources/streetViewContract.ts ***!
  \*********************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   ACTIVE_TILE_CHANNEL: () => (/* binding */ ACTIVE_TILE_CHANNEL),
/* harmony export */   ACTIVE_TILE_REQUEST_CHANNEL: () => (/* binding */ ACTIVE_TILE_REQUEST_CHANNEL),
/* harmony export */   ACTIVE_TILE_REQUEST_SCHEMA: () => (/* binding */ ACTIVE_TILE_REQUEST_SCHEMA),
/* harmony export */   ACTIVE_TILE_SCHEMA: () => (/* binding */ ACTIVE_TILE_SCHEMA),
/* harmony export */   CAMERA_CONTEXT_CHANNEL: () => (/* binding */ CAMERA_CONTEXT_CHANNEL),
/* harmony export */   CAMERA_CONTEXT_SCHEMA: () => (/* binding */ CAMERA_CONTEXT_SCHEMA),
/* harmony export */   INSPECTION_REQUEST_CHANNEL: () => (/* binding */ INSPECTION_REQUEST_CHANNEL),
/* harmony export */   INSPECTION_REQUEST_SCHEMA: () => (/* binding */ INSPECTION_REQUEST_SCHEMA),
/* harmony export */   cameraMatchesTile: () => (/* binding */ cameraMatchesTile),
/* harmony export */   inspectionMatchesTile: () => (/* binding */ inspectionMatchesTile),
/* harmony export */   latestActiveTile: () => (/* binding */ latestActiveTile),
/* harmony export */   latestActiveTileRequest: () => (/* binding */ latestActiveTileRequest),
/* harmony export */   latestCameraContext: () => (/* binding */ latestCameraContext),
/* harmony export */   latestInspectionRequest: () => (/* binding */ latestInspectionRequest),
/* harmony export */   pointFromWgs84: () => (/* binding */ pointFromWgs84),
/* harmony export */   pointToWgs84: () => (/* binding */ pointToWgs84),
/* harmony export */   sourceFingerprint: () => (/* binding */ sourceFingerprint),
/* harmony export */   tileGeometryWgs84: () => (/* binding */ tileGeometryWgs84),
/* harmony export */   validWgs84Point: () => (/* binding */ validWgs84Point)
/* harmony export */ });
function _toConsumableArray(r) { return _arrayWithoutHoles(r) || _iterableToArray(r) || _unsupportedIterableToArray(r) || _nonIterableSpread(); }
function _nonIterableSpread() { throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _iterableToArray(r) { if ("undefined" != typeof Symbol && null != r[Symbol.iterator] || null != r["@@iterator"]) return Array.from(r); }
function _arrayWithoutHoles(r) { if (Array.isArray(r)) return _arrayLikeToArray(r); }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
var ACTIVE_TILE_CHANNEL = 'sidewalk.active-tile';
var ACTIVE_TILE_REQUEST_CHANNEL = 'sidewalk.active-tile-request';
var INSPECTION_REQUEST_CHANNEL = 'sidewalk.inspection-request';
var CAMERA_CONTEXT_CHANNEL = 'sidewalk.camera-context';
var ACTIVE_TILE_SCHEMA = 'io.github.lzml0.sidewalk-stewards/active-tile/v1';
var ACTIVE_TILE_REQUEST_SCHEMA = 'io.github.lzml0.sidewalk-stewards/active-tile-request/v1';
var INSPECTION_REQUEST_SCHEMA = 'io.github.lzml0.sidewalk-stewards/inspection-request/v1';
var CAMERA_CONTEXT_SCHEMA = 'io.github.lzml0.sidewalk-stewards/camera-context/v1';
function latest(interactions, channel) {
  var _events$filter$at$eve, _events$filter$at;
  if (!Array.isArray(interactions)) return null;
  var events = interactions.flatMap(function (entry) {
    var _entry$details, _entry$priority;
    var event = entry === null || entry === void 0 || (_entry$details = entry.details) === null || _entry$details === void 0 ? void 0 : _entry$details[channel];
    return event ? [{
      event: event,
      priority: Number((_entry$priority = entry.priority) !== null && _entry$priority !== void 0 ? _entry$priority : 0)
    }] : [];
  });
  if (!events.length) return null;
  var priority = Math.max.apply(Math, _toConsumableArray(events.map(function (item) {
    return item.priority;
  })));
  return (_events$filter$at$eve = (_events$filter$at = events.filter(function (item) {
    return item.priority === priority;
  }).at(-1)) === null || _events$filter$at === void 0 ? void 0 : _events$filter$at.event) !== null && _events$filter$at$eve !== void 0 ? _events$filter$at$eve : null;
}
function latestActiveTile(interactions) {
  var _event$geometry;
  var event = latest(interactions, ACTIVE_TILE_CHANNEL);
  return (event === null || event === void 0 ? void 0 : event.schema) === ACTIVE_TILE_SCHEMA && typeof event.editorId === 'string' && typeof event.sourceFingerprint === 'string' && typeof event.selectionEpoch === 'string' && Number.isSafeInteger(event.selectionRevision) && event.selectionRevision >= 0 && (event.tileId === null || typeof event.tileId === 'string') && (event.geometry === null || ((_event$geometry = event.geometry) === null || _event$geometry === void 0 ? void 0 : _event$geometry.type) === 'Polygon') && event.crs === 'EPSG:4326' ? event : null;
}
function latestActiveTileRequest(interactions) {
  var event = latest(interactions, ACTIVE_TILE_REQUEST_CHANNEL);
  return (event === null || event === void 0 ? void 0 : event.schema) === ACTIVE_TILE_REQUEST_SCHEMA && typeof event.viewerId === 'string' && (event.viewerEpoch === undefined || typeof event.viewerEpoch === 'string') && Number.isSafeInteger(event.requestRevision) ? event : null;
}
function latestInspectionRequest(interactions) {
  var event = latest(interactions, INSPECTION_REQUEST_CHANNEL);
  return (event === null || event === void 0 ? void 0 : event.schema) === INSPECTION_REQUEST_SCHEMA && typeof event.editorId === 'string' && typeof event.sourceFingerprint === 'string' && typeof event.selectionEpoch === 'string' && Number.isSafeInteger(event.selectionRevision) && event.selectionRevision >= 0 && Number.isSafeInteger(event.requestRevision) && event.requestRevision >= 1 && typeof event.tileId === 'string' && event.tileId.length > 0 && event.crs === 'EPSG:4326' && validWgs84Point(event.location) ? event : null;
}
function latestCameraContext(interactions) {
  var event = latest(interactions, CAMERA_CONTEXT_CHANNEL);
  return (event === null || event === void 0 ? void 0 : event.schema) === CAMERA_CONTEXT_SCHEMA && typeof event.editorId === 'string' && typeof event.sourceFingerprint === 'string' && typeof event.selectionEpoch === 'string' && Number.isSafeInteger(event.selectionRevision) && typeof event.viewerId === 'string' && typeof event.tileId === 'string' && typeof event.imageId === 'string' && Number.isSafeInteger(event.displayRevision) && (event.requestRevision === undefined || event.requestRevision === null || Number.isSafeInteger(event.requestRevision) && event.requestRevision >= 1) && (event.location === null || Array.isArray(event.location) && event.location.length === 2 && event.location.every(Number.isFinite)) && (event.headingDegrees === null || Number.isFinite(event.headingDegrees)) && (event.headingMeaning === null || event.headingMeaning === 'requested-static-image' || event.headingMeaning === 'live-view-direction') ? event : null;
}
function validWgs84Point(point) {
  return Array.isArray(point) && point.length === 2 && point.every(Number.isFinite) && Math.abs(point[0]) <= 180 && Math.abs(point[1]) <= 90;
}
function pointToWgs84(point, crs) {
  if (crs === null || crs === undefined || crs === 'EPSG:4326') {
    if (!validWgs84Point(point)) throw new Error('Inspection point is outside WGS84 coordinates.');
    return [point[0], point[1]];
  }
  if (crs !== 'EPSG:3857') throw new Error("Unsupported tile CRS: ".concat(crs));
  var longitude = point[0] / 6378137 * 180 / Math.PI;
  var latitude = (2 * Math.atan(Math.exp(point[1] / 6378137)) - Math.PI / 2) * 180 / Math.PI;
  if (!validWgs84Point([longitude, latitude])) throw new Error('Inspection point is outside WGS84 coordinates.');
  return [longitude, latitude];
}

/** GeoJSON defaults to WGS84. Explicit Web Mercator is converted, never relabelled. */
function tileGeometryWgs84(feature, crs) {
  var _feature$geometry;
  if (((_feature$geometry = feature.geometry) === null || _feature$geometry === void 0 ? void 0 : _feature$geometry.type) !== 'Polygon') throw new Error('The active tile must be a polygon.');
  var sourceCrs = crs !== null && crs !== void 0 ? crs : 'EPSG:4326';
  if (sourceCrs !== 'EPSG:4326' && sourceCrs !== 'EPSG:3857') throw new Error("Unsupported tile CRS: ".concat(sourceCrs));
  var coordinates = feature.geometry.coordinates.map(function (ring) {
    return ring.map(function (point) {
      if (point.length < 2 || !Number.isFinite(point[0]) || !Number.isFinite(point[1])) throw new Error('Invalid tile coordinate.');
      if (sourceCrs === 'EPSG:4326') return [point[0], point[1]];
      var longitude = point[0] / 6378137 * 180 / Math.PI;
      var latitude = (2 * Math.atan(Math.exp(point[1] / 6378137)) - Math.PI / 2) * 180 / Math.PI;
      return [longitude, latitude];
    });
  });
  if (!coordinates.length || coordinates[0].length < 4) throw new Error('Invalid tile polygon.');
  return {
    type: 'Polygon',
    coordinates: coordinates
  };
}
function pointFromWgs84(point, crs) {
  if (crs === null || crs === undefined || crs === 'EPSG:4326') return [point[0], point[1]];
  if (crs !== 'EPSG:3857') throw new Error("Unsupported tile CRS: ".concat(crs));
  var latitude = Math.max(-85.05112878, Math.min(85.05112878, point[1]));
  return [6378137 * point[0] * Math.PI / 180, 6378137 * Math.log(Math.tan(Math.PI / 4 + latitude * Math.PI / 360))];
}
function sourceFingerprint(sourceIdentity, imageTemplate, networkTemplate, source) {
  var _ref, _sourceValue$path, _sourceValue$metadata;
  if (sourceIdentity) return sourceIdentity;
  var sourceValue = source;
  var identity = typeof sourceValue === 'string' ? sourceValue : (sourceValue === null || sourceValue === void 0 ? void 0 : sourceValue.type) === 'FeatureCollection' && Array.isArray(sourceValue.features) ? sourceValue.features.map(function (feature) {
    var _feature$properties$t, _feature$properties;
    return [(_feature$properties$t = (_feature$properties = feature.properties) === null || _feature$properties === void 0 ? void 0 : _feature$properties.tile_id) !== null && _feature$properties$t !== void 0 ? _feature$properties$t : feature.id, feature.geometry];
  }) : (_ref = (_sourceValue$path = sourceValue === null || sourceValue === void 0 ? void 0 : sourceValue.path) !== null && _sourceValue$path !== void 0 ? _sourceValue$path : sourceValue === null || sourceValue === void 0 || (_sourceValue$metadata = sourceValue.metadata) === null || _sourceValue$metadata === void 0 ? void 0 : _sourceValue$metadata.sourceIdentity) !== null && _ref !== void 0 ? _ref : null;
  var value = JSON.stringify([imageTemplate, networkTemplate, identity]);
  var hash = 2166136261;
  for (var i = 0; i < value.length; i += 1) hash = Math.imul(hash ^ value.charCodeAt(i), 16777619);
  return "fnv1a-".concat((hash >>> 0).toString(16).padStart(8, '0'));
}
function cameraMatchesTile(camera, tile) {
  return tile.tileId !== null && camera.editorId === tile.editorId && camera.sourceFingerprint === tile.sourceFingerprint && camera.selectionEpoch === tile.selectionEpoch && camera.selectionRevision === tile.selectionRevision && camera.tileId === tile.tileId;
}
function inspectionMatchesTile(request, tile) {
  return tile.tileId !== null && request.editorId === tile.editorId && request.sourceFingerprint === tile.sourceFingerprint && request.selectionEpoch === tile.selectionEpoch && request.selectionRevision === tile.selectionRevision && request.tileId === tile.tileId;
}

/***/ },

/***/ "../../../packages/curio.sidewalk-stewards@1/sources/streetViewImages.ts"
/*!*******************************************************************************!*\
  !*** ../../../packages/curio.sidewalk-stewards@1/sources/streetViewImages.ts ***!
  \*******************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   DEFAULT_INSPECTION_DISTANCE_METRES: () => (/* binding */ DEFAULT_INSPECTION_DISTANCE_METRES),
/* harmony export */   distanceMeters: () => (/* binding */ distanceMeters),
/* harmony export */   imagesForRequest: () => (/* binding */ imagesForRequest),
/* harmony export */   imagesForTile: () => (/* binding */ imagesForTile),
/* harmony export */   pointInPolygon: () => (/* binding */ pointInPolygon),
/* harmony export */   polygonCenter: () => (/* binding */ polygonCenter),
/* harmony export */   readStreetImages: () => (/* binding */ readStreetImages),
/* harmony export */   requestedHeading: () => (/* binding */ requestedHeading)
/* harmony export */ });
/* harmony import */ var _resourceResolver__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! ./resourceResolver */ "../../../packages/curio.sidewalk-stewards@1/sources/resourceResolver.ts");
function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
function _slicedToArray(r, e) { return _arrayWithHoles(r) || _iterableToArrayLimit(r, e) || _unsupportedIterableToArray(r, e) || _nonIterableRest(); }
function _nonIterableRest() { throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _iterableToArrayLimit(r, l) { var t = null == r ? null : "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (null != t) { var e, n, i, u, a = [], f = !0, o = !1; try { if (i = (t = t.call(r)).next, 0 === l) { if (Object(t) !== t) return; f = !1; } else for (; !(f = (e = i.call(t)).done) && (a.push(e.value), a.length !== l); f = !0); } catch (r) { o = !0, n = r; } finally { try { if (!f && null != t["return"] && (u = t["return"](), Object(u) !== u)) return; } finally { if (o) throw n; } } return a; } }
function _arrayWithHoles(r) { if (Array.isArray(r)) return r; }
function _regenerator() { /*! regenerator-runtime -- Copyright (c) 2014-present, Facebook, Inc. -- license (MIT): https://github.com/babel/babel/blob/main/packages/babel-helpers/LICENSE */ var e, t, r = "function" == typeof Symbol ? Symbol : {}, n = r.iterator || "@@iterator", o = r.toStringTag || "@@toStringTag"; function i(r, n, o, i) { var c = n && n.prototype instanceof Generator ? n : Generator, u = Object.create(c.prototype); return _regeneratorDefine2(u, "_invoke", function (r, n, o) { var i, c, u, f = 0, p = o || [], y = !1, G = { p: 0, n: 0, v: e, a: d, f: d.bind(e, 4), d: function d(t, r) { return i = t, c = 0, u = e, G.n = r, a; } }; function d(r, n) { for (c = r, u = n, t = 0; !y && f && !o && t < p.length; t++) { var o, i = p[t], d = G.p, l = i[2]; r > 3 ? (o = l === n) && (u = i[(c = i[4]) ? 5 : (c = 3, 3)], i[4] = i[5] = e) : i[0] <= d && ((o = r < 2 && d < i[1]) ? (c = 0, G.v = n, G.n = i[1]) : d < l && (o = r < 3 || i[0] > n || n > l) && (i[4] = r, i[5] = n, G.n = l, c = 0)); } if (o || r > 1) return a; throw y = !0, n; } return function (o, p, l) { if (f > 1) throw TypeError("Generator is already running"); for (y && 1 === p && d(p, l), c = p, u = l; (t = c < 2 ? e : u) || !y;) { i || (c ? c < 3 ? (c > 1 && (G.n = -1), d(c, u)) : G.n = u : G.v = u); try { if (f = 2, i) { if (c || (o = "next"), t = i[o]) { if (!(t = t.call(i, u))) throw TypeError("iterator result is not an object"); if (!t.done) return t; u = t.value, c < 2 && (c = 0); } else 1 === c && (t = i["return"]) && t.call(i), c < 2 && (u = TypeError("The iterator does not provide a '" + o + "' method"), c = 1); i = e; } else if ((t = (y = G.n < 0) ? u : r.call(n, G)) !== a) break; } catch (t) { i = e, c = 1, u = t; } finally { f = 1; } } return { value: t, done: y }; }; }(r, o, i), !0), u; } var a = {}; function Generator() {} function GeneratorFunction() {} function GeneratorFunctionPrototype() {} t = Object.getPrototypeOf; var c = [][n] ? t(t([][n]())) : (_regeneratorDefine2(t = {}, n, function () { return this; }), t), u = GeneratorFunctionPrototype.prototype = Generator.prototype = Object.create(c); function f(e) { return Object.setPrototypeOf ? Object.setPrototypeOf(e, GeneratorFunctionPrototype) : (e.__proto__ = GeneratorFunctionPrototype, _regeneratorDefine2(e, o, "GeneratorFunction")), e.prototype = Object.create(u), e; } return GeneratorFunction.prototype = GeneratorFunctionPrototype, _regeneratorDefine2(u, "constructor", GeneratorFunctionPrototype), _regeneratorDefine2(GeneratorFunctionPrototype, "constructor", GeneratorFunction), GeneratorFunction.displayName = "GeneratorFunction", _regeneratorDefine2(GeneratorFunctionPrototype, o, "GeneratorFunction"), _regeneratorDefine2(u), _regeneratorDefine2(u, o, "Generator"), _regeneratorDefine2(u, n, function () { return this; }), _regeneratorDefine2(u, "toString", function () { return "[object Generator]"; }), (_regenerator = function _regenerator() { return { w: i, m: f }; })(); }
function _regeneratorDefine2(e, r, n, t) { var i = Object.defineProperty; try { i({}, "", {}); } catch (e) { i = 0; } _regeneratorDefine2 = function _regeneratorDefine(e, r, n, t) { function o(r, n) { _regeneratorDefine2(e, r, function (e) { return this._invoke(r, n, e); }); } r ? i ? i(e, r, { value: n, enumerable: !t, configurable: !t, writable: !t }) : e[r] = n : (o("next", 0), o("throw", 1), o("return", 2)); }, _regeneratorDefine2(e, r, n, t); }
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: !0, configurable: !0, writable: !0 }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == _typeof(i) ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != _typeof(t) || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r || "default"); if ("object" != _typeof(i)) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
function _createForOfIteratorHelper(r, e) { var t = "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (!t) { if (Array.isArray(r) || (t = _unsupportedIterableToArray(r)) || e && r && "number" == typeof r.length) { t && (r = t); var _n = 0, F = function F() {}; return { s: F, n: function n() { return _n >= r.length ? { done: !0 } : { done: !1, value: r[_n++] }; }, e: function e(r) { throw r; }, f: F }; } throw new TypeError("Invalid attempt to iterate non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); } var o, a = !0, u = !1; return { s: function s() { t = t.call(r); }, n: function n() { var r = t.next(); return a = r.done, r; }, e: function e(r) { u = !0, o = r; }, f: function f() { try { a || null == t["return"] || t["return"](); } finally { if (u) throw o; } } }; }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
function asyncGeneratorStep(n, t, e, r, o, a, c) { try { var i = n[a](c), u = i.value; } catch (n) { return void e(n); } i.done ? t(u) : Promise.resolve(u).then(r, o); }
function _asyncToGenerator(n) { return function () { var t = this, e = arguments; return new Promise(function (r, o) { var a = n.apply(t, e); function _next(n) { asyncGeneratorStep(a, r, o, _next, _throw, "next", n); } function _throw(n) { asyncGeneratorStep(a, r, o, _next, _throw, "throw", n); } _next(void 0); }); }; }

var DEFAULT_INSPECTION_DISTANCE_METRES = 60;
function unwrap(_x, _x2) {
  return _unwrap.apply(this, arguments);
}
function _unwrap() {
  _unwrap = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee(input, signal) {
    var value, depth, _value, _value2, _value3, _value4, _t;
    return _regenerator().w(function (_context) {
      while (1) switch (_context.p = _context.n) {
        case 0:
          value = input; // Data Loading produces a dict artifact reference, whereas Street View
          // Fetcher produces a geodataframe. Both use Curio's public /get route.
          depth = 0;
        case 1:
          if (!(depth < 8)) {
            _context.n = 13;
            break;
          }
          if (!(typeof value === 'string')) {
            _context.n = 6;
            break;
          }
          if (value.trim()) {
            _context.n = 2;
            break;
          }
          return _context.a(2, null);
        case 2:
          _context.p = 2;
          value = JSON.parse(value);
          _context.n = 5;
          break;
        case 3:
          _context.p = 3;
          _t = _context.v;
          _context.n = 4;
          return (0,_resourceResolver__WEBPACK_IMPORTED_MODULE_0__.fetchData)(value, signal);
        case 4:
          value = _context.v;
        case 5:
          _context.n = 12;
          break;
        case 6:
          if (!((_value = value) !== null && _value !== void 0 && _value.path && !value.data)) {
            _context.n = 8;
            break;
          }
          _context.n = 7;
          return (0,_resourceResolver__WEBPACK_IMPORTED_MODULE_0__.fetchData)(value.path, signal);
        case 7:
          value = _context.v;
          _context.n = 12;
          break;
        case 8:
          if (!['dict', 'geodataframe', 'geojson'].includes((_value2 = value) === null || _value2 === void 0 ? void 0 : _value2.dataType)) {
            _context.n = 9;
            break;
          }
          value = value.data;
          _context.n = 12;
          break;
        case 9:
          if (!(((_value3 = value) === null || _value3 === void 0 || (_value3 = _value3.data) === null || _value3 === void 0 ? void 0 : _value3.type) === 'FeatureCollection')) {
            _context.n = 10;
            break;
          }
          value = value.data;
          _context.n = 12;
          break;
        case 10:
          if (!(((_value4 = value) === null || _value4 === void 0 || (_value4 = _value4.content) === null || _value4 === void 0 ? void 0 : _value4.type) === 'FeatureCollection')) {
            _context.n = 11;
            break;
          }
          value = value.content;
          _context.n = 12;
          break;
        case 11:
          return _context.a(2, value);
        case 12:
          depth += 1;
          _context.n = 1;
          break;
        case 13:
          throw new Error('Street View input contains too many nested references.');
        case 14:
          return _context.a(2);
      }
    }, _callee, null, [[2, 3]]);
  }));
  return _unwrap.apply(this, arguments);
}
function readStreetImages(_x3, _x4) {
  return _readStreetImages.apply(this, arguments);
}

/** Parse only the public request parameter; never return or log the keyed URL. */
function _readStreetImages() {
  _readStreetImages = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee2(input, signal) {
    var value, collection, images, unavailable, _iterator2, _step2, _feature$geometry, _feature$properties, _ref, _ref2, _props$pano_id, _step2$value, index, feature, coords, props, url, id, heading, _t2;
    return _regenerator().w(function (_context2) {
      while (1) switch (_context2.p = _context2.n) {
        case 0:
          _context2.n = 1;
          return unwrap(input, signal);
        case 1:
          value = _context2.v;
          if (value) {
            _context2.n = 2;
            break;
          }
          return _context2.a(2, {
            images: [],
            unavailable: 0
          });
        case 2:
          if (!(value.type !== 'FeatureCollection' || !Array.isArray(value.features))) {
            _context2.n = 3;
            break;
          }
          throw new Error('Street View input must be a point FeatureCollection.');
        case 3:
          collection = value;
          images = [];
          unavailable = 0;
          _iterator2 = _createForOfIteratorHelper(collection.features.entries());
          _context2.p = 4;
          _iterator2.s();
        case 5:
          if ((_step2 = _iterator2.n()).done) {
            _context2.n = 8;
            break;
          }
          _step2$value = _slicedToArray(_step2.value, 2), index = _step2$value[0], feature = _step2$value[1];
          coords = ((_feature$geometry = feature.geometry) === null || _feature$geometry === void 0 ? void 0 : _feature$geometry.type) === 'Point' ? feature.geometry.coordinates : null;
          if (!(!Array.isArray(coords) || coords.length < 2 || !Number.isFinite(coords[0]) || !Number.isFinite(coords[1]) || Math.abs(coords[0]) > 180 || Math.abs(coords[1]) > 90)) {
            _context2.n = 6;
            break;
          }
          unavailable += 1;
          return _context2.a(3, 7);
        case 6:
          props = (_feature$properties = feature.properties) !== null && _feature$properties !== void 0 ? _feature$properties : {};
          url = typeof props.image_url === 'string' && props.image_url.trim() ? props.image_url : null;
          id = String((_ref = (_ref2 = (_props$pano_id = props.pano_id) !== null && _props$pano_id !== void 0 ? _props$pano_id : props.image_id) !== null && _ref2 !== void 0 ? _ref2 : feature.id) !== null && _ref !== void 0 ? _ref : "image-".concat(index + 1));
          heading = requestedHeading(url);
          images.push({
            id: id,
            location: [coords[0], coords[1]],
            imageUrl: url,
            requestedHeading: heading,
            date: typeof props.date === 'string' && props.date ? props.date : null
          });
          if (!url) unavailable += 1;
        case 7:
          _context2.n = 5;
          break;
        case 8:
          _context2.n = 10;
          break;
        case 9:
          _context2.p = 9;
          _t2 = _context2.v;
          _iterator2.e(_t2);
        case 10:
          _context2.p = 10;
          _iterator2.f();
          return _context2.f(10);
        case 11:
          return _context2.a(2, {
            images: images,
            unavailable: unavailable
          });
      }
    }, _callee2, null, [[4, 9, 10, 11]]);
  }));
  return _readStreetImages.apply(this, arguments);
}
function requestedHeading(url) {
  if (!url) return null;
  try {
    var raw = new URL(url, 'http://localhost').searchParams.get('heading');
    if (raw === null || raw.trim() === '') return null;
    var value = Number(raw);
    return Number.isFinite(value) ? (value % 360 + 360) % 360 : null;
  } catch (_unused) {
    return null;
  }
}
function polygonCenter(polygon) {
  var _polygon$coordinates$, _points$at, _points$at2;
  var points = (_polygon$coordinates$ = polygon.coordinates[0]) !== null && _polygon$coordinates$ !== void 0 ? _polygon$coordinates$ : [];
  var unique = points.length > 1 && points[0][0] === ((_points$at = points.at(-1)) === null || _points$at === void 0 ? void 0 : _points$at[0]) && points[0][1] === ((_points$at2 = points.at(-1)) === null || _points$at2 === void 0 ? void 0 : _points$at2[1]) ? points.slice(0, -1) : points;
  return [unique.reduce(function (sum, p) {
    return sum + p[0];
  }, 0) / unique.length, unique.reduce(function (sum, p) {
    return sum + p[1];
  }, 0) / unique.length];
}
function distanceMeters(a, b) {
  var rad = Math.PI / 180;
  var phi1 = a[1] * rad,
    phi2 = b[1] * rad;
  var deltaPhi = (b[1] - a[1]) * rad,
    deltaLambda = (b[0] - a[0]) * rad;
  var h = Math.pow(Math.sin(deltaPhi / 2), 2) + Math.cos(phi1) * Math.cos(phi2) * Math.pow(Math.sin(deltaLambda / 2), 2);
  return 2 * 6371008.8 * Math.asin(Math.min(1, Math.sqrt(h)));
}
function pointInPolygon(point, polygon) {
  var inRing = function inRing(ring) {
    var inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var a = ring[i],
        b = ring[j];
      var cross = (point[0] - a[0]) * (b[1] - a[1]) - (point[1] - a[1]) * (b[0] - a[0]);
      if (Math.abs(cross) < 1e-12 && point[0] >= Math.min(a[0], b[0]) - 1e-12 && point[0] <= Math.max(a[0], b[0]) + 1e-12 && point[1] >= Math.min(a[1], b[1]) - 1e-12 && point[1] <= Math.max(a[1], b[1]) + 1e-12) return true;
      if (a[1] > point[1] !== b[1] > point[1] && point[0] < (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
    }
    return inside;
  };
  return !!polygon.coordinates[0] && inRing(polygon.coordinates[0]) && !polygon.coordinates.slice(1).some(inRing);
}
function distanceToBoundary(point, polygon) {
  var center = polygonCenter(polygon);
  var scaleX = 111320 * Math.cos(center[1] * Math.PI / 180),
    scaleY = 111320;
  var nearest = Infinity;
  var _iterator = _createForOfIteratorHelper(polygon.coordinates),
    _step;
  try {
    for (_iterator.s(); !(_step = _iterator.n()).done;) {
      var ring = _step.value;
      for (var i = 1; i < ring.length; i += 1) {
        var a = ring[i - 1],
          b = ring[i];
        var ax = (a[0] - point[0]) * scaleX,
          ay = (a[1] - point[1]) * scaleY;
        var dx = (b[0] - a[0]) * scaleX,
          dy = (b[1] - a[1]) * scaleY;
        var t = Math.max(0, Math.min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy || 1)));
        nearest = Math.min(nearest, Math.hypot(ax + t * dx, ay + t * dy));
      }
    }
  } catch (err) {
    _iterator.e(err);
  } finally {
    _iterator.f();
  }
  return nearest;
}

/** Prefer in-tile records; the explicit nearby fallback is at most 30 m outside the polygon. */
function imagesForTile(images, polygon) {
  var fallbackMetres = arguments.length > 2 && arguments[2] !== undefined ? arguments[2] : 30;
  var center = polygonCenter(polygon);
  var inside = images.filter(function (image) {
    return pointInPolygon(image.location, polygon);
  });
  var choices = inside.length ? inside : images.filter(function (image) {
    return distanceToBoundary(image.location, polygon) <= fallbackMetres;
  });
  return choices.map(function (image) {
    return _objectSpread(_objectSpread({}, image), {}, {
      outside: !pointInPolygon(image.location, polygon),
      distanceFromCenter: distanceMeters(center, image.location)
    });
  }).sort(function (a, b) {
    return a.distanceFromCenter - b.distanceFromCenter || a.id.localeCompare(b.id);
  });
}

/** A point request uses the actual camera point, not a tile-centre substitute. */
function imagesForRequest(images, polygon, requested) {
  var maxDistanceMetres = arguments.length > 3 && arguments[3] !== undefined ? arguments[3] : DEFAULT_INSPECTION_DISTANCE_METRES;
  var center = polygonCenter(polygon);
  return images.filter(function (image) {
    return !!image.imageUrl && Number.isFinite(image.location[0]) && Number.isFinite(image.location[1]);
  }).map(function (image) {
    return _objectSpread(_objectSpread({}, image), {}, {
      outside: !pointInPolygon(image.location, polygon),
      distanceFromCenter: distanceMeters(center, image.location),
      distanceFromRequest: distanceMeters(requested, image.location)
    });
  }).filter(function (image) {
    return image.distanceFromRequest <= maxDistanceMetres;
  }).sort(function (a, b) {
    return a.distanceFromRequest - b.distanceFromRequest || a.id.localeCompare(b.id);
  });
}

/***/ },

/***/ "../../../packages/curio.sidewalk-stewards@1/sources/tileNeighbors.ts"
/*!****************************************************************************!*\
  !*** ../../../packages/curio.sidewalk-stewards@1/sources/tileNeighbors.ts ***!
  \****************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   TILE_DIRECTIONS: () => (/* binding */ TILE_DIRECTIONS),
/* harmony export */   buildTileNeighborIndex: () => (/* binding */ buildTileNeighborIndex),
/* harmony export */   tileAtPoint: () => (/* binding */ tileAtPoint)
/* harmony export */ });
/* harmony import */ var _sidewalkEditOperations__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! ./sidewalkEditOperations */ "../../../packages/curio.sidewalk-stewards@1/sources/sidewalkEditOperations.ts");
function _toConsumableArray(r) { return _arrayWithoutHoles(r) || _iterableToArray(r) || _unsupportedIterableToArray(r) || _nonIterableSpread(); }
function _nonIterableSpread() { throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _iterableToArray(r) { if ("undefined" != typeof Symbol && null != r[Symbol.iterator] || null != r["@@iterator"]) return Array.from(r); }
function _arrayWithoutHoles(r) { if (Array.isArray(r)) return _arrayLikeToArray(r); }
function _slicedToArray(r, e) { return _arrayWithHoles(r) || _iterableToArrayLimit(r, e) || _unsupportedIterableToArray(r, e) || _nonIterableRest(); }
function _nonIterableRest() { throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _iterableToArrayLimit(r, l) { var t = null == r ? null : "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (null != t) { var e, n, i, u, a = [], f = !0, o = !1; try { if (i = (t = t.call(r)).next, 0 === l) { if (Object(t) !== t) return; f = !1; } else for (; !(f = (e = i.call(t)).done) && (a.push(e.value), a.length !== l); f = !0); } catch (r) { o = !0, n = r; } finally { try { if (!f && null != t["return"] && (u = t["return"](), Object(u) !== u)) return; } finally { if (o) throw n; } } return a; } }
function _arrayWithHoles(r) { if (Array.isArray(r)) return r; }
function _createForOfIteratorHelper(r, e) { var t = "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (!t) { if (Array.isArray(r) || (t = _unsupportedIterableToArray(r)) || e && r && "number" == typeof r.length) { t && (r = t); var _n = 0, F = function F() {}; return { s: F, n: function n() { return _n >= r.length ? { done: !0 } : { done: !1, value: r[_n++] }; }, e: function e(r) { throw r; }, f: F }; } throw new TypeError("Invalid attempt to iterate non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); } var o, a = !0, u = !1; return { s: function s() { t = t.call(r); }, n: function n() { var r = t.next(); return a = r.done, r; }, e: function e(r) { u = !0, o = r; }, f: function f() { try { a || null == t["return"] || t["return"](); } finally { if (u) throw o; } } }; }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }

var TILE_DIRECTIONS = ['north', 'south', 'east', 'west'];
var tileId = function tileId(feature) {
  var _ref, _ref2, _feature$properties$t, _feature$properties, _feature$properties2;
  return String((_ref = (_ref2 = (_feature$properties$t = (_feature$properties = feature.properties) === null || _feature$properties === void 0 ? void 0 : _feature$properties.tile_id) !== null && _feature$properties$t !== void 0 ? _feature$properties$t : (_feature$properties2 = feature.properties) === null || _feature$properties2 === void 0 ? void 0 : _feature$properties2.tileId) !== null && _ref2 !== void 0 ? _ref2 : feature.id) !== null && _ref !== void 0 ? _ref : '');
};
var integer = function integer(value) {
  return Number.isSafeInteger(Number(value)) && value !== null && value !== '' ? Number(value) : null;
};
var bucket = function bucket(coordinate, tolerance) {
  return Math.round(coordinate / tolerance);
};
var cellKey = function cellKey(zoom, x, y) {
  return "".concat(zoom, "/").concat(x, "/").concat(y);
};
function boundarySegments(feature, bounds, tolerance) {
  var sides = {
    north: [],
    south: [],
    east: [],
    west: []
  };
  var geometry = feature.geometry;
  var rings = (geometry === null || geometry === void 0 ? void 0 : geometry.type) === 'Polygon' ? geometry.coordinates : (geometry === null || geometry === void 0 ? void 0 : geometry.type) === 'MultiPolygon' ? geometry.coordinates.flat() : [];
  var _iterator = _createForOfIteratorHelper(rings),
    _step;
  try {
    for (_iterator.s(); !(_step = _iterator.n()).done;) {
      var ring = _step.value;
      for (var i = 1; i < ring.length; i += 1) {
        var a = ring[i - 1];
        var b = ring[i];
        if (Math.abs(a[1] - b[1]) <= tolerance && Math.abs(a[0] - b[0]) > tolerance) {
          var segment = [Math.min(a[0], b[0]), Math.max(a[0], b[0])];
          if (Math.abs(a[1] - bounds[3]) <= tolerance) sides.north.push(segment);
          if (Math.abs(a[1] - bounds[1]) <= tolerance) sides.south.push(segment);
        }
        if (Math.abs(a[0] - b[0]) <= tolerance && Math.abs(a[1] - b[1]) > tolerance) {
          var _segment = [Math.min(a[1], b[1]), Math.max(a[1], b[1])];
          if (Math.abs(a[0] - bounds[2]) <= tolerance) sides.east.push(_segment);
          if (Math.abs(a[0] - bounds[0]) <= tolerance) sides.west.push(_segment);
        }
      }
    }
  } catch (err) {
    _iterator.e(err);
  } finally {
    _iterator.f();
  }
  return sides;
}
function sharedSide(a, b, direction, tolerance) {
  var opposite = {
    north: 'south',
    south: 'north',
    east: 'west',
    west: 'east'
  };
  var _ref3 = direction === 'north' ? [3, 1] : direction === 'south' ? [1, 3] : direction === 'east' ? [2, 0] : [0, 2],
    _ref4 = _slicedToArray(_ref3, 2),
    ai = _ref4[0],
    bi = _ref4[1];
  if (Math.abs(a.bounds[ai] - b.bounds[bi]) > tolerance) return 0;
  var overlap = 0;
  var _iterator2 = _createForOfIteratorHelper(a.sides[direction]),
    _step2;
  try {
    for (_iterator2.s(); !(_step2 = _iterator2.n()).done;) {
      var first = _step2.value;
      var _iterator3 = _createForOfIteratorHelper(b.sides[opposite[direction]]),
        _step3;
      try {
        for (_iterator3.s(); !(_step3 = _iterator3.n()).done;) {
          var second = _step3.value;
          overlap += Math.max(0, Math.min(first[1], second[1]) - Math.max(first[0], second[0]));
        }
      } catch (err) {
        _iterator3.e(err);
      } finally {
        _iterator3.f();
      }
    }
  } catch (err) {
    _iterator2.e(err);
  } finally {
    _iterator2.f();
  }
  return overlap > tolerance ? overlap : 0;
}

/** Build once per prepared grid/source revision; never infer adjacency from tile IDs. */
function buildTileNeighborIndex(grid) {
  var raw = grid.features.flatMap(function (feature) {
    var id = tileId(feature);
    var bounds = (0,_sidewalkEditOperations__WEBPACK_IMPORTED_MODULE_0__.featureBounds)(feature);
    return id && bounds ? [{
      id: id,
      feature: feature,
      bounds: bounds
    }] : [];
  });
  var dimensions = raw.flatMap(function (_ref5) {
    var bounds = _ref5.bounds;
    return [bounds[2] - bounds[0], bounds[3] - bounds[1]];
  }).filter(function (value) {
    return value > 0;
  });
  var tolerance = dimensions.reduce(function (minimum, value) {
    return Math.min(minimum, value);
  }, 1) * 1e-5;
  var cells = raw.map(function (_ref6) {
    var _feature$properties3, _feature$properties4, _feature$properties5;
    var id = _ref6.id,
      feature = _ref6.feature,
      bounds = _ref6.bounds;
    return {
      id: id,
      feature: feature,
      bounds: bounds,
      x: integer((_feature$properties3 = feature.properties) === null || _feature$properties3 === void 0 ? void 0 : _feature$properties3.x),
      y: integer((_feature$properties4 = feature.properties) === null || _feature$properties4 === void 0 ? void 0 : _feature$properties4.y),
      zoom: integer((_feature$properties5 = feature.properties) === null || _feature$properties5 === void 0 ? void 0 : _feature$properties5.zoom),
      sides: boundarySegments(feature, bounds, tolerance)
    };
  });
  var features = new Map(cells.map(function (cell) {
    return [cell.id, cell.feature];
  }));
  var positions = new Map(grid.features.map(function (feature, position) {
    return [tileId(feature), position];
  }));
  var metadata = new Map();
  var sideBuckets = new Map();
  var _iterator4 = _createForOfIteratorHelper(cells),
    _step4;
  try {
    for (_iterator4.s(); !(_step4 = _iterator4.n()).done;) {
      var cell = _step4.value;
      if (cell.x !== null && cell.y !== null && cell.zoom !== null) metadata.set(cellKey(cell.zoom, cell.x, cell.y), cell);
      for (var _i = 0, _arr = [['north', cell.bounds[3]], ['south', cell.bounds[1]], ['east', cell.bounds[2]], ['west', cell.bounds[0]]]; _i < _arr.length; _i++) {
        var _arr$_i = _slicedToArray(_arr[_i], 2),
          direction = _arr$_i[0],
          coordinate = _arr$_i[1];
        var key = "".concat(direction, ":").concat(bucket(coordinate, tolerance));
        var existing = sideBuckets.get(key);
        if (existing) existing.push(cell);else sideBuckets.set(key, [cell]);
      }
    }
  } catch (err) {
    _iterator4.e(err);
  } finally {
    _iterator4.f();
  }
  var opposite = {
    north: 'south',
    south: 'north',
    east: 'west',
    west: 'east'
  };
  var neighbors = new Map();
  var _iterator5 = _createForOfIteratorHelper(cells),
    _step5;
  try {
    var _loop = function _loop() {
      var cell = _step5.value;
      var result = {};
      var _iterator6 = _createForOfIteratorHelper(TILE_DIRECTIONS),
        _step6;
      try {
        var _loop2 = function _loop2() {
          var direction = _step6.value;
          var _ref7 = direction === 'north' ? [0, -1] : direction === 'south' ? [0, 1] : direction === 'east' ? [1, 0] : [-1, 0],
            _ref8 = _slicedToArray(_ref7, 2),
            dx = _ref8[0],
            dy = _ref8[1];
          var byMetadata = cell.x !== null && cell.y !== null && cell.zoom !== null ? metadata.get(cellKey(cell.zoom, cell.x + dx, cell.y + dy)) : undefined;
          var candidates = new Set();
          if (byMetadata) candidates.add(byMetadata);
          var coordinate = direction === 'north' ? cell.bounds[3] : direction === 'south' ? cell.bounds[1] : direction === 'east' ? cell.bounds[2] : cell.bounds[0];
          var center = bucket(coordinate, tolerance);
          for (var offset = -1; offset <= 1; offset += 1) {
            var _sideBuckets$get;
            var _iterator7 = _createForOfIteratorHelper((_sideBuckets$get = sideBuckets.get("".concat(opposite[direction], ":").concat(center + offset))) !== null && _sideBuckets$get !== void 0 ? _sideBuckets$get : []),
              _step7;
            try {
              for (_iterator7.s(); !(_step7 = _iterator7.n()).done;) {
                var candidate = _step7.value;
                candidates.add(candidate);
              }
            } catch (err) {
              _iterator7.e(err);
            } finally {
              _iterator7.f();
            }
          }
          var ranked = _toConsumableArray(candidates).filter(function (candidate) {
            return candidate !== cell;
          }).map(function (candidate) {
            return {
              candidate: candidate,
              overlap: sharedSide(cell, candidate, direction, tolerance)
            };
          }).filter(function (item) {
            return item.overlap > 0;
          }).sort(function (a, b) {
            return b.overlap - a.overlap || a.candidate.id.localeCompare(b.candidate.id);
          });
          if (ranked.length) result[direction] = ranked[0].candidate.id;
        };
        for (_iterator6.s(); !(_step6 = _iterator6.n()).done;) {
          _loop2();
        }
      } catch (err) {
        _iterator6.e(err);
      } finally {
        _iterator6.f();
      }
      neighbors.set(cell.id, result);
    };
    for (_iterator5.s(); !(_step5 = _iterator5.n()).done;) {
      _loop();
    }
  } catch (err) {
    _iterator5.e(err);
  } finally {
    _iterator5.f();
  }
  return {
    features: features,
    bounds: new Map(cells.map(function (cell) {
      return [cell.id, cell.bounds];
    })),
    positions: positions,
    neighbors: neighbors
  };
}

/** Resolve an actual camera position against the prepared grid, only on explicit adoption. */
function tileAtPoint(index, point) {
  var _iterator8 = _createForOfIteratorHelper(index.bounds),
    _step8;
  try {
    for (_iterator8.s(); !(_step8 = _iterator8.n()).done;) {
      var _feature$geometry;
      var _step8$value = _slicedToArray(_step8.value, 2),
        id = _step8$value[0],
        bounds = _step8$value[1];
      if (point[0] < bounds[0] || point[0] > bounds[2] || point[1] < bounds[1] || point[1] > bounds[3]) continue;
      var feature = index.features.get(id);
      if ((feature === null || feature === void 0 || (_feature$geometry = feature.geometry) === null || _feature$geometry === void 0 ? void 0 : _feature$geometry.type) === 'Polygon') {
        var _feature$geometry$coo;
        // Grid cells are rectangular in the canonical example, but respect the polygon itself.
        var ring = (_feature$geometry$coo = feature.geometry.coordinates[0]) !== null && _feature$geometry$coo !== void 0 ? _feature$geometry$coo : [];
        var inside = false;
        for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
          var a = ring[i],
            b = ring[j];
          if (a[1] > point[1] !== b[1] > point[1] && point[0] < (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
        }
        if (!inside) continue;
      }
      return id;
    }
  } catch (err) {
    _iterator8.e(err);
  } finally {
    _iterator8.f();
  }
  return null;
}

/***/ },

/***/ "../../../packages/curio.sidewalk-stewards@1/sources/useSidewalkOverview.ts"
/*!**********************************************************************************!*\
  !*** ../../../packages/curio.sidewalk-stewards@1/sources/useSidewalkOverview.ts ***!
  \**********************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   useSidewalkOverview: () => (/* binding */ useSidewalkOverview)
/* harmony export */ });
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! react */ "react");
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(react__WEBPACK_IMPORTED_MODULE_0__);
/* harmony import */ var _beforeAfterContext__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! ./beforeAfterContext */ "../../../packages/curio.sidewalk-stewards@1/sources/beforeAfterContext.ts");
/* harmony import */ var _resourceResolver__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(/*! ./resourceResolver */ "../../../packages/curio.sidewalk-stewards@1/sources/resourceResolver.ts");
/* harmony import */ var _overviewData__WEBPACK_IMPORTED_MODULE_3__ = __webpack_require__(/*! ./overviewData */ "../../../packages/curio.sidewalk-stewards@1/sources/overviewData.ts");
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





/** Publishes committed geometry independently of active tile and transient selection echoes. */
function useSidewalkOverview(config, emit, supplied) {
  var identity = config.overview ? (0,_overviewData__WEBPACK_IMPORTED_MODULE_3__.overviewIdentity)(config) : '';
  var _useState = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState2 = _slicedToArray(_useState, 2),
    loaded = _useState2[0],
    setLoaded = _useState2[1];
  var _useState3 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(''),
    _useState4 = _slicedToArray(_useState3, 2),
    error = _useState4[0],
    setError = _useState4[1];
  var refs = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)({
    config: config,
    emit: emit
  });
  refs.current = {
    config: config,
    emit: emit
  };
  var published = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)('');
  var latestOutput = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)(undefined);
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    setLoaded(null);
    setError('');
    published.current = '';
    latestOutput.current = undefined;
    if (!identity) return;
    if (supplied) {
      setLoaded({
        identity: identity,
        context: supplied
      });
      return;
    }
    if (refs.current.config.mode === 'input-overview') return;
    var controller = new AbortController();
    var overview = refs.current.config.overview;
    if (Object.values(overview).some(function (value) {
      return !value.trim();
    })) {
      setError('Overview dataset ID and all three resource paths are required.');
      return function () {
        return controller.abort();
      };
    }
    var load = /*#__PURE__*/function () {
      var _ref = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee(path) {
        var response, value;
        return _regenerator().w(function (_context) {
          while (1) switch (_context.n) {
            case 0:
              _context.n = 1;
              return fetch((0,_resourceResolver__WEBPACK_IMPORTED_MODULE_2__.assetUrl)(path), {
                signal: controller.signal
              });
            case 1:
              response = _context.v;
              if (response.ok) {
                _context.n = 2;
                break;
              }
              throw new Error("Overview resource failed (HTTP ".concat(response.status, "): ").concat(path));
            case 2:
              _context.n = 3;
              return response.json();
            case 3:
              value = _context.v;
              if (!((value === null || value === void 0 ? void 0 : value.type) !== 'FeatureCollection' || !Array.isArray(value.features))) {
                _context.n = 4;
                break;
              }
              throw new Error("Overview resource is not a GeoJSON FeatureCollection: ".concat(path));
            case 4:
              return _context.a(2, value);
          }
        }, _callee);
      }));
      return function load(_x) {
        return _ref.apply(this, arguments);
      };
    }();
    Promise.all([load(overview.gridUrl), load(overview.networkUrl), load(overview.boundariesUrl)]).then(function (_ref2) {
      var _ref3 = _slicedToArray(_ref2, 3),
        grid = _ref3[0],
        network = _ref3[1],
        boundaries = _ref3[2];
      if (controller.signal.aborted) return;
      var context = {
        grid: grid,
        network: network,
        boundaries: boundaries
      };
      (0,_overviewData__WEBPACK_IMPORTED_MODULE_3__.validateOverview)(context);
      setLoaded({
        identity: identity,
        context: context
      });
    })["catch"](function (e) {
      if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e));
    });
    return function () {
      return controller.abort();
    };
  }, [identity, supplied]);
  var context = (loaded === null || loaded === void 0 ? void 0 : loaded.identity) === identity ? loaded.context : null;
  var signature = context ? (0,_overviewData__WEBPACK_IMPORTED_MODULE_3__.committedSignature)(config, context.grid) : '';
  var publish = function publish(next, latest) {
    if (!context) return;
    if (latest !== undefined) latestOutput.current = latest;
    var output = supplied ? (0,_beforeAfterContext__WEBPACK_IMPORTED_MODULE_1__.contextOutput)(supplied, next, latestOutput.current) : (0,_overviewData__WEBPACK_IMPORTED_MODULE_3__.buildOverview)(context, next, latestOutput.current);
    var content = (0,_overviewData__WEBPACK_IMPORTED_MODULE_3__.stableJson)(output);
    if (content === published.current) return;
    published.current = content;
    refs.current.emit(output);
  };
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    if (context) publish(refs.current.config);
    // Selection, drafts, and callback identity do not change committed geometry.
  }, [context, signature]);
  return {
    context: context,
    error: error,
    loading: !!identity && !context && !error,
    publish: publish
  };
}

/***/ },

/***/ "../../../packages/curio.streetvision@1/sources/nodeUiStyles.ts"
/*!**********************************************************************!*\
  !*** ../../../packages/curio.streetvision@1/sources/nodeUiStyles.ts ***!
  \**********************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   nodeUiStyles: () => (/* binding */ nodeUiStyles)
/* harmony export */ });
/** Shared presentation for Street Vision and connected editor node bodies. */
var nodeUiStyles = {
  root: {
    padding: '12px 14px',
    fontFamily: '"Roboto","Helvetica","Arial",sans-serif',
    fontSize: 13,
    color: '#333',
    display: 'flex',
    flexDirection: 'column',
    gap: 10
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 2
  },
  logo: {
    width: 28,
    height: 28,
    borderRadius: 6,
    background: 'linear-gradient(135deg,#3b82f6,#60a5fa)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: '#fff',
    fontSize: 14,
    fontWeight: 700,
    flexShrink: 0
  },
  title: {
    fontSize: 14,
    fontWeight: 600,
    color: '#1a1a2e',
    lineHeight: 1.2
  },
  sub: {
    fontSize: 10,
    color: '#888',
    marginTop: 1
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    fontSize: 11,
    color: '#666'
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    flexShrink: 0
  },
  input: {
    width: '100%',
    padding: '7px 10px',
    border: '1px solid #e2e8f0',
    borderRadius: 6,
    fontSize: 12,
    outline: 'none',
    boxSizing: 'border-box'
  },
  btn: {
    padding: '8px 12px',
    border: 'none',
    borderRadius: 8,
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    transition: 'all 0.15s',
    width: '100%'
  },
  btnPrimary: {
    background: 'linear-gradient(135deg,#3b82f6,#2563eb)',
    color: '#fff'
  },
  btnSecondary: {
    background: '#f1f5f9',
    color: '#334155',
    border: '1px solid #e2e8f0'
  },
  btnDisabled: {
    background: '#f3f4f6',
    color: '#9ca3af',
    border: '1px solid #e5e7eb',
    cursor: 'not-allowed'
  },
  card: {
    background: '#f8fafc',
    border: '1px solid #e2e8f0',
    borderRadius: 8,
    padding: '10px 12px',
    fontSize: 12
  },
  label: {
    fontSize: 10,
    fontWeight: 600,
    textTransform: 'uppercase',
    color: '#94a3b8',
    letterSpacing: 1,
    marginBottom: 4
  },
  helper: {
    fontSize: 11,
    color: '#64748b',
    marginTop: 4
  },
  warn: {
    color: '#92400e',
    background: '#fef9c3',
    borderColor: '#fde68a',
    fontSize: 11
  },
  err: {
    color: '#991b1b',
    background: '#fef2f2',
    border: '1px solid #fecaca',
    borderRadius: 6,
    padding: '6px 8px',
    fontSize: 11
  }
};

/***/ },

/***/ "../../../packages/curio.streetvision@1/sources/panoramaContract.ts"
/*!**************************************************************************!*\
  !*** ../../../packages/curio.streetvision@1/sources/panoramaContract.ts ***!
  \**************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   PANORAMA_CAMERA_CHANNEL: () => (/* binding */ PANORAMA_CAMERA_CHANNEL),
/* harmony export */   PANORAMA_CAMERA_SCHEMA: () => (/* binding */ PANORAMA_CAMERA_SCHEMA),
/* harmony export */   PANORAMA_CONTEXT_CHANNEL: () => (/* binding */ PANORAMA_CONTEXT_CHANNEL),
/* harmony export */   PANORAMA_CONTEXT_SCHEMA: () => (/* binding */ PANORAMA_CONTEXT_SCHEMA),
/* harmony export */   PANORAMA_REQUEST_CHANNEL: () => (/* binding */ PANORAMA_REQUEST_CHANNEL),
/* harmony export */   PANORAMA_REQUEST_SCHEMA: () => (/* binding */ PANORAMA_REQUEST_SCHEMA),
/* harmony export */   PANORAMA_STATUS_CHANNEL: () => (/* binding */ PANORAMA_STATUS_CHANNEL),
/* harmony export */   PANORAMA_STATUS_SCHEMA: () => (/* binding */ PANORAMA_STATUS_SCHEMA),
/* harmony export */   latestPanoramaCamera: () => (/* binding */ latestPanoramaCamera),
/* harmony export */   latestPanoramaContext: () => (/* binding */ latestPanoramaContext),
/* harmony export */   latestPanoramaRequest: () => (/* binding */ latestPanoramaRequest),
/* harmony export */   latestPanoramaStatus: () => (/* binding */ latestPanoramaStatus),
/* harmony export */   readPanoramaRequest: () => (/* binding */ readPanoramaRequest),
/* harmony export */   validPoint: () => (/* binding */ validPoint)
/* harmony export */ });
function _toConsumableArray(r) { return _arrayWithoutHoles(r) || _iterableToArray(r) || _unsupportedIterableToArray(r) || _nonIterableSpread(); }
function _nonIterableSpread() { throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _iterableToArray(r) { if ("undefined" != typeof Symbol && null != r[Symbol.iterator] || null != r["@@iterator"]) return Array.from(r); }
function _arrayWithoutHoles(r) { if (Array.isArray(r)) return _arrayLikeToArray(r); }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
/** Public, versioned interaction contract. Coordinates are WGS84 [longitude, latitude]. */
var PANORAMA_REQUEST_CHANNEL = 'curio.panorama.request';
var PANORAMA_CAMERA_CHANNEL = 'curio.panorama.camera';
var PANORAMA_CONTEXT_CHANNEL = 'curio.panorama.context';
var PANORAMA_STATUS_CHANNEL = 'curio.panorama.status';
var PANORAMA_REQUEST_SCHEMA = 'curio.streetvision/panorama-request/v1';
var PANORAMA_CAMERA_SCHEMA = 'curio.streetvision/panorama-camera/v1';
var PANORAMA_CONTEXT_SCHEMA = 'curio.streetvision/panorama-context/v1';
var PANORAMA_STATUS_SCHEMA = 'curio.streetvision/panorama-status/v1';
function latestPanoramaStatus(interactions) {
  var _candidates$filter$at, _candidates$filter$at2;
  if (!Array.isArray(interactions)) return null;
  var candidates = interactions.flatMap(function (entry) {
    var _entry$details, _entry$priority;
    var status = entry === null || entry === void 0 || (_entry$details = entry.details) === null || _entry$details === void 0 ? void 0 : _entry$details[PANORAMA_STATUS_CHANNEL];
    return (status === null || status === void 0 ? void 0 : status.schema) === PANORAMA_STATUS_SCHEMA && typeof status.requestId === 'string' && Number.isSafeInteger(status.revision) && typeof status.viewerId === 'string' && ['missing-key', 'invalid-key', 'loading', 'unavailable', 'error', 'confirmed'].includes(status.state) ? [{
      status: status,
      priority: Number((_entry$priority = entry.priority) !== null && _entry$priority !== void 0 ? _entry$priority : 0)
    }] : [];
  });
  if (!candidates.length) return null;
  var priority = Math.max.apply(Math, _toConsumableArray(candidates.map(function (entry) {
    return entry.priority;
  })));
  return (_candidates$filter$at = (_candidates$filter$at2 = candidates.filter(function (entry) {
    return entry.priority === priority;
  }).at(-1)) === null || _candidates$filter$at2 === void 0 ? void 0 : _candidates$filter$at2.status) !== null && _candidates$filter$at !== void 0 ? _candidates$filter$at : null;
}
function validPoint(value) {
  return Array.isArray(value) && value.length === 2 && value.every(Number.isFinite) && Math.abs(value[0]) <= 180 && Math.abs(value[1]) <= 90;
}
function readPanoramaRequest(value) {
  var _value$reuseCurrent, _value$reuseCurrent2;
  if (!value || value.schema !== PANORAMA_REQUEST_SCHEMA || typeof value.requestId !== 'string' || !value.requestId || !Number.isSafeInteger(value.revision) || value.revision < 0 || value.crs !== 'EPSG:4326' || !validPoint(value.location)) return null;
  if (value.radiusMetres !== undefined && (!Number.isFinite(value.radiusMetres) || value.radiusMetres < 1 || value.radiusMetres > 1000)) return null;
  if (value.initialHeadingDegrees !== undefined && !Number.isFinite(value.initialHeadingDegrees)) return null;
  if (value.reuseCurrent !== undefined && (typeof ((_value$reuseCurrent = value.reuseCurrent) === null || _value$reuseCurrent === void 0 ? void 0 : _value$reuseCurrent.viewerId) !== 'string' || !value.reuseCurrent.viewerId || typeof ((_value$reuseCurrent2 = value.reuseCurrent) === null || _value$reuseCurrent2 === void 0 ? void 0 : _value$reuseCurrent2.panoId) !== 'string')) return null;
  return value;
}
function latestPanoramaRequest(interactions) {
  var _candidates$filter$at3, _candidates$filter$at4;
  if (!Array.isArray(interactions)) return null;
  var candidates = interactions.flatMap(function (entry) {
    var _entry$details2, _entry$priority2;
    var request = readPanoramaRequest(entry === null || entry === void 0 || (_entry$details2 = entry.details) === null || _entry$details2 === void 0 ? void 0 : _entry$details2[PANORAMA_REQUEST_CHANNEL]);
    return request ? [{
      request: request,
      priority: Number((_entry$priority2 = entry.priority) !== null && _entry$priority2 !== void 0 ? _entry$priority2 : 0)
    }] : [];
  });
  if (!candidates.length) return null;
  var priority = Math.max.apply(Math, _toConsumableArray(candidates.map(function (entry) {
    return entry.priority;
  })));
  return (_candidates$filter$at3 = (_candidates$filter$at4 = candidates.filter(function (entry) {
    return entry.priority === priority;
  }).at(-1)) === null || _candidates$filter$at4 === void 0 ? void 0 : _candidates$filter$at4.request) !== null && _candidates$filter$at3 !== void 0 ? _candidates$filter$at3 : null;
}
function latestPanoramaCamera(interactions) {
  var _candidates$filter$at5, _candidates$filter$at6;
  if (!Array.isArray(interactions)) return null;
  var candidates = interactions.flatMap(function (entry) {
    var _entry$details3, _entry$priority3;
    var camera = entry === null || entry === void 0 || (_entry$details3 = entry.details) === null || _entry$details3 === void 0 ? void 0 : _entry$details3[PANORAMA_CAMERA_CHANNEL];
    return (camera === null || camera === void 0 ? void 0 : camera.schema) === PANORAMA_CAMERA_SCHEMA && typeof camera.requestId === 'string' && Number.isSafeInteger(camera.revision) && Number.isSafeInteger(camera.cameraRevision) && typeof camera.viewerId === 'string' && validPoint(camera.actualLocation) && validPoint(camera.requestedLocation) && Number.isFinite(camera.headingDegrees) && camera.headingReference === 'clockwise-from-true-north' ? [{
      camera: camera,
      priority: Number((_entry$priority3 = entry.priority) !== null && _entry$priority3 !== void 0 ? _entry$priority3 : 0)
    }] : [];
  });
  if (!candidates.length) return null;
  var priority = Math.max.apply(Math, _toConsumableArray(candidates.map(function (entry) {
    return entry.priority;
  })));
  return (_candidates$filter$at5 = (_candidates$filter$at6 = candidates.filter(function (entry) {
    return entry.priority === priority;
  }).at(-1)) === null || _candidates$filter$at6 === void 0 ? void 0 : _candidates$filter$at6.camera) !== null && _candidates$filter$at5 !== void 0 ? _candidates$filter$at5 : null;
}
function latestPanoramaContext(interactions) {
  var _event$filter$at$cont, _event$filter$at;
  var event = Array.isArray(interactions) ? interactions.flatMap(function (entry) {
    var _entry$details4, _entry$priority4;
    var context = entry === null || entry === void 0 || (_entry$details4 = entry.details) === null || _entry$details4 === void 0 ? void 0 : _entry$details4[PANORAMA_CONTEXT_CHANNEL];
    return (context === null || context === void 0 ? void 0 : context.schema) === PANORAMA_CONTEXT_SCHEMA && typeof context.requestId === 'string' && Number.isSafeInteger(context.revision) && context.active === false ? [{
      context: context,
      priority: Number((_entry$priority4 = entry.priority) !== null && _entry$priority4 !== void 0 ? _entry$priority4 : 0)
    }] : [];
  }) : [];
  if (!event.length) return null;
  var priority = Math.max.apply(Math, _toConsumableArray(event.map(function (item) {
    return item.priority;
  })));
  return (_event$filter$at$cont = (_event$filter$at = event.filter(function (item) {
    return item.priority === priority;
  }).at(-1)) === null || _event$filter$at === void 0 ? void 0 : _event$filter$at.context) !== null && _event$filter$at$cont !== void 0 ? _event$filter$at$cont : null;
}

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
/*!*********************************************************************!*\
  !*** ../../../packages/curio.sidewalk-stewards@1/sources/index.tsx ***!
  \*********************************************************************/
__webpack_require__.r(__webpack_exports__);
/* harmony import */ var _sidewalkTileEditBehavior__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! ./sidewalkTileEditBehavior */ "../../../packages/curio.sidewalk-stewards@1/sources/sidewalkTileEditBehavior.tsx");
/* harmony import */ var _sidewalkPreparation__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! ./sidewalkPreparation */ "../../../packages/curio.sidewalk-stewards@1/sources/sidewalkPreparation.tsx");


function register(curio) {
  curio.registerBehavior('sidewalk-tile-edit', _sidewalkTileEditBehavior__WEBPACK_IMPORTED_MODULE_0__.useSidewalkTileEditBehavior);
  curio.registerBehavior('sidewalk-prepare', _sidewalkPreparation__WEBPACK_IMPORTED_MODULE_1__.useSidewalkPreparation);
}
if (typeof window !== 'undefined') {
  var _host$curio;
  var host = window;
  if (typeof ((_host$curio = host.curio) === null || _host$curio === void 0 ? void 0 : _host$curio.registerBehavior) === 'function') register(host.curio);else {
    var _host$__curioPendingP;
    var pending = (_host$__curioPendingP = host.__curioPendingPackages__) !== null && _host$__curioPendingP !== void 0 ? _host$__curioPendingP : host.__curioPendingPackages__ = [];
    pending.push(register);
  }
}
})();

/******/ 	return __webpack_exports__;
/******/ })()
;
});
//# sourceMappingURL=behaviors.js.map