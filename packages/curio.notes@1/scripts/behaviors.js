(function webpackUniversalModuleDefinition(root, factory) {
	if(typeof exports === 'object' && typeof module === 'object')
		module.exports = factory(require("react"));
	else if(typeof define === 'function' && define.amd)
		define(["react"], factory);
	else if(typeof exports === 'object')
		exports["curio_notes_1"] = factory(require("react"));
	else
		root["curio_notes_1"] = factory(root["React"]);
})(this, (__WEBPACK_EXTERNAL_MODULE_react__) => {
return /******/ (() => { // webpackBootstrap
/******/ 	"use strict";
/******/ 	var __webpack_modules__ = ({

/***/ "../../../packages/curio.notes@1/sources/noteBehavior.tsx"
/*!****************************************************************!*\
  !*** ../../../packages/curio.notes@1/sources/noteBehavior.tsx ***!
  \****************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   inline: () => (/* binding */ inline),
/* harmony export */   noteColor: () => (/* binding */ noteColor),
/* harmony export */   renderMarkdown: () => (/* binding */ renderMarkdown),
/* harmony export */   textColor: () => (/* binding */ textColor),
/* harmony export */   useNoteBehavior: () => (/* binding */ useNoteBehavior)
/* harmony export */ });
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! react */ "react");
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(react__WEBPACK_IMPORTED_MODULE_0__);
function _createForOfIteratorHelper(r, e) { var t = "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (!t) { if (Array.isArray(r) || (t = _unsupportedIterableToArray(r)) || e && r && "number" == typeof r.length) { t && (r = t); var _n = 0, F = function F() {}; return { s: F, n: function n() { return _n >= r.length ? { done: !0 } : { done: !1, value: r[_n++] }; }, e: function e(r) { throw r; }, f: F }; } throw new TypeError("Invalid attempt to iterate non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); } var o, a = !0, u = !1; return { s: function s() { t = t.call(r); }, n: function n() { var r = t.next(); return a = r.done, r; }, e: function e(r) { u = !0, o = r; }, f: function f() { try { a || null == t["return"] || t["return"](); } finally { if (u) throw o; } } }; }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }

/**
 * Note: a post-it on the canvas.
 *
 * The node's content is its text (`data.code`, also read as `data.content`)
 * and `data.appearance.backgroundColor` its color, as the Researcher agent
 * writes them. The text is simple markdown, drawn as React elements, never as
 * HTML: `#`/`##` headings, `- ` bullets, `**bold**`, and `[label](https://…)`
 * links (any other link is shown as text). A note runs nothing: it has no
 * handles, and a run counts it done at once (`disablePlay`).
 */

var PALETTE = {
  yellow: '#fff3b0',
  pink: '#ffd6e0',
  blue: '#cfe8ff',
  green: '#d5f5d0',
  orange: '#ffe0b8',
  lavender: '#e6dcff'
};
var HEX = /^#[0-9a-fA-F]{6}$/;
function noteColor(raw) {
  if (typeof raw !== 'string') return PALETTE.yellow;
  var key = raw.trim().toLowerCase();
  if (PALETTE[key]) return PALETTE[key];
  return HEX.test(raw.trim()) ? raw.trim() : PALETTE.yellow;
}

/** Dark text on a light note, light text on a dark one. */
function textColor(background) {
  var n = parseInt(background.slice(1), 16);
  var r = n >> 16 & 255,
    g = n >> 8 & 255,
    b = n & 255;
  return 0.299 * r + 0.587 * g + 0.114 * b > 140 ? '#1e1f23' : '#ffffff';
}
var INLINE = /(\*\*[^*]+\*\*|\[[^\]]+\]\([^)\s]+\))/g;

/** One line's bold spans and links, as React elements. */
function inline(text, keyPrefix) {
  var out = [];
  var last = 0;
  var index = 0;
  var _iterator = _createForOfIteratorHelper(text.matchAll(INLINE)),
    _step;
  try {
    for (_iterator.s(); !(_step = _iterator.n()).done;) {
      var _match$index;
      var match = _step.value;
      var at = (_match$index = match.index) !== null && _match$index !== void 0 ? _match$index : 0;
      if (at > last) out.push(text.slice(last, at));
      var token = match[0];
      var key = "".concat(keyPrefix, "-").concat(index++);
      if (token.startsWith('**')) {
        out.push(/*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("strong", {
          key: key
        }, token.slice(2, -2)));
      } else {
        var label = token.slice(1, token.indexOf(']('));
        var href = token.slice(token.indexOf('](') + 2, -1);
        out.push(/^https:\/\//.test(href) ? /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("a", {
          key: key,
          href: href,
          target: "_blank",
          rel: "noopener noreferrer",
          style: {
            color: 'inherit'
          }
        }, label) : "".concat(label, " (").concat(href, ")"));
      }
      last = at + token.length;
    }
  } catch (err) {
    _iterator.e(err);
  } finally {
    _iterator.f();
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** The note's text as blocks: headings, bullet lists and paragraphs. */
function renderMarkdown(text) {
  var blocks = [];
  var bullets = [];
  var flush = function flush() {
    if (!bullets.length) return;
    var at = blocks.length;
    blocks.push(/*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("ul", {
      key: "ul-".concat(at),
      style: {
        margin: '4px 0',
        paddingLeft: 18
      }
    }, bullets.map(function (item, i) {
      return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("li", {
        key: i
      }, inline(item, "li-".concat(at, "-").concat(i)));
    })));
    bullets = [];
  };
  text.split(/\r?\n/).forEach(function (raw, i) {
    var line = raw.trimEnd();
    if (/^\s*[-*] /.test(line)) {
      bullets.push(line.replace(/^\s*[-*] /, ''));
      return;
    }
    flush();
    if (!line.trim()) return;
    var heading = line.match(/^(#{1,3}) (.*)$/);
    if (heading) {
      blocks.push(/*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
        key: "h-".concat(i),
        style: {
          fontWeight: 700,
          fontSize: heading[1].length === 1 ? 15 : 13,
          margin: '6px 0 2px'
        }
      }, inline(heading[2], "h-".concat(i))));
      return;
    }
    blocks.push(/*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("p", {
      key: "p-".concat(i),
      style: {
        margin: '4px 0'
      }
    }, inline(line, "p-".concat(i))));
  });
  flush();
  return blocks;
}
var useNoteBehavior = function useNoteBehavior(data) {
  var _content, _appearance;
  var raw = (_content = data === null || data === void 0 ? void 0 : data.content) !== null && _content !== void 0 ? _content : data === null || data === void 0 ? void 0 : data.code;
  var text = typeof raw === 'string' ? raw : '';
  var background = noteColor(data === null || data === void 0 || (_appearance = data.appearance) === null || _appearance === void 0 ? void 0 : _appearance.backgroundColor);
  var color = textColor(background);
  return {
    disablePlay: true,
    handlesOverride: [],
    contentComponent: /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      className: "nowheel",
      "data-testid": "curio-note",
      style: {
        background: background,
        color: color,
        borderRadius: 6,
        padding: '10px 12px',
        fontSize: 12.5,
        lineHeight: 1.45,
        maxHeight: 360,
        overflowY: 'auto',
        boxShadow: '0 2px 6px rgba(0, 0, 0, 0.12)'
      }
    }, text.trim() ? renderMarkdown(text) : /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
      style: {
        opacity: 0.6
      }
    }, "An empty note."))
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
/*!*********************************************************!*\
  !*** ../../../packages/curio.notes@1/sources/index.tsx ***!
  \*********************************************************/
__webpack_require__.r(__webpack_exports__);
/* harmony import */ var _noteBehavior__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! ./noteBehavior */ "../../../packages/curio.notes@1/sources/noteBehavior.tsx");
/**
 * Bundle entry point for the Notes package.
 *
 * Webpack compiles this file into `../scripts/behaviors.js`; Curio evaluates
 * that bundle at boot, which registers the `note` behavior named by the
 * template in manifest.json. React and ReactFlow are Curio's own, on `window`.
 */


function registerAll(curio) {
  curio.registerBehavior('note', _noteBehavior__WEBPACK_IMPORTED_MODULE_0__.useNoteBehavior);
}
if (typeof window !== 'undefined') {
  var w = window;
  if (w.curio && typeof w.curio.registerBehavior === 'function') {
    registerAll(w.curio);
  } else {
    var _w$__curioPendingPack;
    // This bundle can load before Curio publishes its registry: queue it.
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