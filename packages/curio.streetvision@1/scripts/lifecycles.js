(function webpackUniversalModuleDefinition(root, factory) {
	if(typeof exports === 'object' && typeof module === 'object')
		module.exports = factory(require("react"));
	else if(typeof define === 'function' && define.amd)
		define(["react"], factory);
	else if(typeof exports === 'object')
		exports["curio_streetvision_1"] = factory(require("react"));
	else
		root["curio_streetvision_1"] = factory(root["React"]);
})(this, (__WEBPACK_EXTERNAL_MODULE_react__) => {
return /******/ (() => { // webpackBootstrap
/******/ 	"use strict";
/******/ 	var __webpack_modules__ = ({

/***/ "../../../packages/curio.streetvision@1/sources/cvGalleryLifecycle.tsx"
/*!*****************************************************************************!*\
  !*** ../../../packages/curio.streetvision@1/sources/cvGalleryLifecycle.tsx ***!
  \*****************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   useCvGalleryLifecycle: () => (/* binding */ useCvGalleryLifecycle)
/* harmony export */ });
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! react */ "react");
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(react__WEBPACK_IMPORTED_MODULE_0__);
function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
var _curio;
function _toConsumableArray(r) { return _arrayWithoutHoles(r) || _iterableToArray(r) || _unsupportedIterableToArray(r) || _nonIterableSpread(); }
function _nonIterableSpread() { throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _iterableToArray(r) { if ("undefined" != typeof Symbol && null != r[Symbol.iterator] || null != r["@@iterator"]) return Array.from(r); }
function _arrayWithoutHoles(r) { if (Array.isArray(r)) return _arrayLikeToArray(r); }
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

/**
 * CV Gallery lifecycle.
 *
 * Receives the inference results JSON emitted by HF CV Inference upstream
 * (shape: `{type:'street_vision_results', results: ResultItem[], ...}`).
 * Renders a gallery + per-image inspector + aggregate stats panel, then
 * pushes the data downstream as a GEODATAFRAME-shaped FeatureCollection so
 * downstream nodes (Spatial Join, Vega-Lite, AUTK Map, …) consume it cleanly.
 *
 * Adapted from
 *   utk_curio/frontend/urban-workflows/src/adapters/node/cvAnalysisLifecycle.tsx
 * in ManeeshJupalle/curio (feat/street-vision-cv-analysis, #120). The
 * neighborhood-enrichment + Vega-Lite-template parts of the original have
 * been factored out — neighborhood tagging is now the separate generic
 * Spatial Join node (curio.builtin@1/spatial-join), and Vega-Lite specs
 * live in the user-facing docs example.
 */

// See streetViewFetcherLifecycle for the rationale on runtime URL resolution.
var API_BASE = "".concat(typeof window !== 'undefined' && ((_curio = window.curio) === null || _curio === void 0 ? void 0 : _curio.backendUrl) || '', "/api/streetvision");
// Cityscapes-flavored palette; kept in sync with the inference service's
// overlay PNG palette so colors in the gallery match colors in the overlays.
var CLASS_COLORS = {
  road: '#4A90D9',
  sidewalk: '#8B5CF6',
  building: '#2ECC71',
  wall: '#95A5A6',
  fence: '#BDC3C7',
  pole: '#E74C3C',
  'traffic light': '#F39C12',
  'traffic sign': '#E67E22',
  vegetation: '#F5A623',
  terrain: '#1ABC9C',
  sky: '#3498DB',
  person: '#9B59B6',
  rider: '#C0392B',
  car: '#2C3E50',
  truck: '#7F8C8D',
  bus: '#D35400',
  train: '#16A085',
  motorcycle: '#8E44AD',
  bicycle: '#27AE60'
};
var DEFAULT_COLOR = '#94a3b8';
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
    background: 'linear-gradient(135deg,#8b5cf6,#a78bfa)',
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
  link: {
    background: 'none',
    border: 'none',
    color: '#8b5cf6',
    fontSize: 11,
    fontWeight: 600,
    cursor: 'pointer',
    marginLeft: 'auto',
    padding: '4px 8px'
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
    width: '100%'
  },
  btnGreen: {
    background: '#f0fdf4',
    color: '#166534',
    border: '1px solid #bbf7d0'
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
  badge: {
    display: 'inline-block',
    padding: '2px 6px',
    borderRadius: 4,
    fontSize: 10,
    fontWeight: 600
  },
  sectionLabel: {
    fontSize: 10,
    fontWeight: 600,
    textTransform: 'uppercase',
    color: '#94a3b8',
    letterSpacing: 1,
    marginBottom: 4
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(2, 1fr)',
    gap: 8,
    marginTop: 6
  },
  gridCard: {
    border: '1px solid #e2e8f0',
    borderRadius: 8,
    overflow: 'hidden',
    cursor: 'pointer',
    background: '#fff'
  },
  gridImg: {
    width: '100%',
    height: 90,
    objectFit: 'cover',
    display: 'block',
    background: '#f1f5f9'
  },
  gridInfo: {
    padding: '6px 8px',
    fontSize: 10,
    color: '#64748b'
  },
  tabBar: {
    display: 'flex',
    gap: 2,
    marginBottom: 10
  },
  tab: {
    padding: '5px 10px',
    fontSize: 11,
    fontWeight: 500,
    cursor: 'pointer',
    border: 'none',
    borderBottom: '2px solid transparent',
    background: 'none',
    color: '#64748b'
  },
  tabActive: {
    borderBottomColor: '#8b5cf6',
    color: '#8b5cf6',
    fontWeight: 600
  },
  statsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(2, 1fr)',
    gap: 6,
    marginTop: 6
  },
  statCard: {
    background: '#f8fafc',
    border: '1px solid #e2e8f0',
    borderRadius: 8,
    padding: '8px 10px',
    textAlign: 'center'
  },
  statValue: {
    fontSize: 18,
    fontWeight: 700,
    color: '#1a1a2e'
  },
  statLabel: {
    fontSize: 9,
    color: '#94a3b8',
    textTransform: 'uppercase',
    marginTop: 2
  }
};

// Convert results → GEODATAFRAME-shaped FeatureCollection. The Table view +
// Vega-Lite both read `feature.properties.*` and `feature.geometry`.
function buildFeatureCollection(results) {
  var round = function round(n, places) {
    return n == null ? null : Number(n.toFixed(places));
  };
  // Union of all detected class keys so the table doesn't show holes when
  // one image didn't surface a class that another did.
  var allClassKeys = new Set();
  results.forEach(function (r) {
    if (r.class_ratios) Object.keys(r.class_ratios).forEach(function (k) {
      return allClassKeys.add(k);
    });
    if (r.object_counts) Object.keys(r.object_counts).forEach(function (k) {
      return allClassKeys.add(k);
    });
  });
  var features = results.map(function (r) {
    var lat = round(r.latitude, 5);
    var lon = round(r.longitude, 5);
    var props = {
      image_id: r.image_id,
      image_url: r.image_url,
      latitude: lat,
      longitude: lon
    };
    allClassKeys.forEach(function (k) {
      props[k] = 0;
    });
    if (r.class_ratios) {
      Object.entries(r.class_ratios).forEach(function (_ref) {
        var _ref2 = _slicedToArray(_ref, 2),
          k = _ref2[0],
          v = _ref2[1];
        props[k] = round(v * 100, 1);
      });
      props.analysis_type = 'segmentation';
    }
    if (r.object_counts) {
      Object.entries(r.object_counts).forEach(function (_ref3) {
        var _ref4 = _slicedToArray(_ref3, 2),
          k = _ref4[0],
          v = _ref4[1];
        props[k] = v;
      });
      props.analysis_type = 'detection';
    }
    var dominantClass = null;
    var dominantPct = -Infinity;
    allClassKeys.forEach(function (k) {
      var v = props[k];
      if (typeof v === 'number' && v > dominantPct) {
        dominantPct = v;
        dominantClass = k;
      }
    });
    props.dominant_class = dominantClass;
    props.dominant_pct = dominantPct === -Infinity ? 0 : dominantPct;
    return {
      type: 'Feature',
      geometry: lat != null && lon != null ? {
        type: 'Point',
        coordinates: [lon, lat]
      } : null,
      properties: props
    };
  });
  return {
    type: 'FeatureCollection',
    features: features,
    metadata: {
      name: 'cv_inference_results'
    }
  };
}
var useCvGalleryLifecycle = function useCvGalleryLifecycle(data, nodeState) {
  var _inspectedItem$longit;
  var _useState = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)('waiting'),
    _useState2 = _slicedToArray(_useState, 2),
    view = _useState2[0],
    setView = _useState2[1];
  var _useState3 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState4 = _slicedToArray(_useState3, 2),
    payload = _useState4[0],
    setPayload = _useState4[1];
  var _useState5 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)([]),
    _useState6 = _slicedToArray(_useState5, 2),
    results = _useState6[0],
    setResults = _useState6[1];
  var _useState7 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState8 = _slicedToArray(_useState7, 2),
    inspectIdx = _useState8[0],
    setInspectIdx = _useState8[1];
  var _useState9 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)('source'),
    _useState0 = _slicedToArray(_useState9, 2),
    inspectTab = _useState0[0],
    setInspectTab = _useState0[1];
  var _useState1 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(false),
    _useState10 = _slicedToArray(_useState1, 2),
    pushed = _useState10[0],
    setPushed = _useState10[1];
  var _useState11 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)('gallery'),
    _useState12 = _slicedToArray(_useState11, 2),
    activeGalleryTab = _useState12[0],
    setActiveGalleryTab = _useState12[1];
  var _useState13 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState14 = _slicedToArray(_useState13, 2),
    pushError = _useState14[0],
    setPushError = _useState14[1];

  // Receive results from upstream.
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    if (data.input == null || data.input === '') return;
    try {
      var raw = typeof data.input === 'string' ? JSON.parse(data.input) : data.input;
      // Accept either the explicit `street_vision_results` envelope OR a bare
      // ResultItem[] (forward-compat for users wiring custom inference nodes).
      var nextResults = [];
      var nextPayload = null;
      if (Array.isArray(raw)) {
        nextResults = raw;
        nextPayload = {
          results: nextResults,
          total_images: nextResults.length
        };
      } else if (raw && raw.type === 'street_vision_results' && Array.isArray(raw.results)) {
        nextResults = raw.results;
        nextPayload = raw;
      } else if (raw && Array.isArray(raw.results)) {
        nextResults = raw.results;
        nextPayload = raw;
      }
      if (nextResults.length > 0) {
        setPayload(nextPayload);
        setResults(nextResults);
        setView('gallery');
        setPushed(false);
      }
    } catch (_unused) {
      // Not parseable — ignore. The waiting view stays up.
    }
  }, [data.input]);
  var imgSrc = function imgSrc(item) {
    var raw = item.image_url || '';
    if (raw.startsWith('/api/')) return "".concat(API_BASE.replace(/\/api\/streetvision$/, '')).concat(raw);
    return raw;
  };
  var overlayUrl = function overlayUrl(item) {
    return !item.demo_mode && item.class_ratios ? "".concat(API_BASE, "/inference/overlay/").concat(encodeURIComponent(item.image_id)) : null;
  };
  var aggStats = results.length > 0 ? function () {
    var allClasses = new Map();
    results.forEach(function (r) {
      if (r.class_ratios) {
        Object.entries(r.class_ratios).forEach(function (_ref5) {
          var _ref6 = _slicedToArray(_ref5, 2),
            k = _ref6[0],
            v = _ref6[1];
          if (!allClasses.has(k)) allClasses.set(k, []);
          allClasses.get(k).push(v);
        });
      }
      if (r.object_counts) {
        Object.entries(r.object_counts).forEach(function (_ref7) {
          var _ref8 = _slicedToArray(_ref7, 2),
            k = _ref8[0],
            v = _ref8[1];
          if (!allClasses.has(k)) allClasses.set(k, []);
          allClasses.get(k).push(v);
        });
      }
    });
    var averages = {};
    allClasses.forEach(function (vals, key) {
      averages[key] = vals.reduce(function (a, b) {
        return a + b;
      }, 0) / vals.length;
    });
    var withGeo = results.filter(function (r) {
      return r.latitude != null;
    }).length;
    return {
      averages: averages,
      classCount: allClasses.size,
      geoCount: withGeo
    };
  }() : null;
  var pushDownstream = (0,react__WEBPACK_IMPORTED_MODULE_0__.useCallback)(function () {
    if (results.length === 0) return;
    setPushError(null);
    try {
      var fc = buildFeatureCollection(results);
      data.outputCallback(data.nodeId, {
        data: fc,
        dataType: 'geodataframe'
      });
      nodeState.setOutput({
        code: 'success',
        content: ''
      });
      setPushed(true);
    } catch (e) {
      setPushError("Push failed: ".concat(e.message));
    }
  }, [results, data, nodeState]);
  var inspectedItem = inspectIdx !== null ? results[inspectIdx] : null;
  var isSegmentation = (payload === null || payload === void 0 ? void 0 : payload.model_type) === 'segmentation';
  var contentComponent = /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.root
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.header
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.logo
  }, "CV"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", null, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.title
  }, "CV Gallery"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.sub
  }, "Inference results inspector")), view === 'inspect' && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    style: S.link,
    onClick: function onClick() {
      setInspectIdx(null);
      setView('gallery');
    }
  }, "\u2190 Gallery")), view === 'waiting' && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: _objectSpread(_objectSpread({}, S.card), {}, {
      textAlign: 'center',
      padding: '24px 16px'
    })
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      fontSize: 32,
      marginBottom: 8,
      opacity: 0.3
    }
  }, "\uD83D\uDD0D"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      fontWeight: 600,
      color: '#334155',
      marginBottom: 4
    }
  }, "Waiting for Data"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      fontSize: 11,
      color: '#94a3b8',
      lineHeight: 1.5
    }
  }, "Connect an ", /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("strong", null, "HF CV Inference"), " node upstream and run it. Results will appear here automatically.")), view === 'gallery' && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement((react__WEBPACK_IMPORTED_MODULE_0___default().Fragment), null, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 6,
      fontSize: 12
    }
  }, (payload === null || payload === void 0 ? void 0 : payload.model_type) && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
    style: _objectSpread(_objectSpread({}, S.badge), {}, {
      background: '#f3e8ff',
      color: '#7c3aed'
    })
  }, payload.model_type), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
    style: {
      color: '#334155',
      fontWeight: 600
    }
  }, results.length, " result", results.length !== 1 ? 's' : '')), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.tabBar
  }, [['gallery', 'Gallery'], ['stats', 'Aggregate Stats']].map(function (_ref9) {
    var _ref0 = _slicedToArray(_ref9, 2),
      k = _ref0[0],
      label = _ref0[1];
    return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
      key: k,
      style: _objectSpread(_objectSpread({}, S.tab), activeGalleryTab === k ? S.tabActive : {}),
      onClick: function onClick() {
        return setActiveGalleryTab(k);
      }
    }, label);
  })), activeGalleryTab === 'gallery' && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: _objectSpread(_objectSpread({}, S.grid), {}, {
      maxHeight: 360,
      overflowY: 'auto'
    })
  }, results.map(function (item, i) {
    return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      key: item.image_id || i,
      style: S.gridCard,
      onClick: function onClick() {
        setInspectIdx(i);
        setInspectTab('source');
        setView('inspect');
      }
    }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("img", {
      src: imgSrc(item),
      alt: item.image_id,
      style: S.gridImg,
      onError: function onError(e) {
        e.target.style.background = '#e2e8f0';
      }
    }), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      style: S.gridInfo
    }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      title: item.image_id,
      style: {
        fontWeight: 600,
        color: '#334155',
        marginBottom: 2,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap'
      }
    }, item.image_id && item.image_id.length > 6 ? item.image_id.slice(0, 6) + '…' : item.image_id), item.class_ratios && Object.entries(item.class_ratios).slice(0, 3).map(function (_ref1) {
      var _ref10 = _slicedToArray(_ref1, 2),
        k = _ref10[0],
        v = _ref10[1];
      return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
        key: k,
        style: {
          marginRight: 6
        }
      }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
        style: {
          display: 'inline-block',
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: CLASS_COLORS[k] || DEFAULT_COLOR,
          marginRight: 2,
          verticalAlign: 'middle'
        }
      }), k, ": ", (v * 100).toFixed(0), "%");
    }), item.object_counts && Object.entries(item.object_counts).slice(0, 3).map(function (_ref11) {
      var _ref12 = _slicedToArray(_ref11, 2),
        k = _ref12[0],
        v = _ref12[1];
      return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
        key: k,
        style: {
          marginRight: 6
        }
      }, k, ": ", v);
    })));
  })), activeGalleryTab === 'stats' && aggStats && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 10
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.statsGrid
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.statCard
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.statValue
  }, results.length), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.statLabel
  }, "Images")), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.statCard
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.statValue
  }, aggStats.classCount), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.statLabel
  }, "Classes")), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.statCard
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.statValue
  }, aggStats.geoCount), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.statLabel
  }, "Geo-located")), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.statCard
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.statValue
  }, (payload === null || payload === void 0 ? void 0 : payload.model_type) === 'segmentation' ? 'Seg' : 'Det'), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.statLabel
  }, "Analysis"))), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", null, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.sectionLabel
  }, isSegmentation ? 'Avg. Class Distribution' : 'Avg. Object Counts'), Object.entries(aggStats.averages).sort(function (_ref13, _ref14) {
    var _ref15 = _slicedToArray(_ref13, 2),
      a = _ref15[1];
    var _ref16 = _slicedToArray(_ref14, 2),
      b = _ref16[1];
    return b - a;
  }).map(function (_ref17) {
    var _ref18 = _slicedToArray(_ref17, 2),
      cls = _ref18[0],
      avg = _ref18[1];
    return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      key: cls,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        marginBottom: 4
      }
    }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
      style: {
        display: 'inline-block',
        width: 8,
        height: 8,
        borderRadius: 2,
        background: CLASS_COLORS[cls] || DEFAULT_COLOR,
        flexShrink: 0
      }
    }), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
      style: {
        fontSize: 11,
        color: '#64748b',
        width: 70,
        textAlign: 'right'
      }
    }, cls), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      style: {
        flex: 1,
        height: 8,
        background: '#e2e8f0',
        borderRadius: 4,
        overflow: 'hidden'
      }
    }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      style: {
        height: '100%',
        width: isSegmentation ? "".concat(avg * 100, "%") : "".concat(Math.min(avg / Math.max.apply(Math, _toConsumableArray(Object.values(aggStats.averages))) * 100, 100), "%"),
        background: CLASS_COLORS[cls] || DEFAULT_COLOR,
        borderRadius: 4,
        transition: 'width 0.3s'
      }
    })), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
      style: {
        fontSize: 10,
        color: '#334155',
        width: 40,
        textAlign: 'right',
        fontWeight: 600
      }
    }, isSegmentation ? "".concat((avg * 100).toFixed(1), "%") : avg.toFixed(1)));
  }))), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    style: _objectSpread(_objectSpread({}, S.btn), results.length > 0 ? S.btnGreen : S.btnDisabled),
    onClick: pushDownstream,
    disabled: results.length === 0
  }, pushed ? '✓ Data Pushed — Re-push' : '▶ Push to Downstream'), pushed && !pushError && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      fontSize: 10,
      color: '#22c55e',
      textAlign: 'center'
    }
  }, results.length, " features pushed as GEODATAFRAME"), pushError && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      fontSize: 10,
      color: '#92400e',
      textAlign: 'center',
      padding: '6px 8px',
      background: '#fef9c3',
      border: '1px solid #fde68a',
      borderRadius: 6
    }
  }, pushError)), view === 'inspect' && inspectedItem && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      position: 'relative'
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.tabBar
  }, [['source', 'Source'], ['overlay', 'CV Overlay'], ['side', 'Side by Side']].map(function (_ref19) {
    var _ref20 = _slicedToArray(_ref19, 2),
      k = _ref20[0],
      label = _ref20[1];
    return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
      key: k,
      style: _objectSpread(_objectSpread({}, S.tab), inspectTab === k ? S.tabActive : {}),
      onClick: function onClick() {
        return setInspectTab(k);
      }
    }, label);
  })), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      display: inspectTab === 'side' ? 'grid' : 'block',
      gridTemplateColumns: '1fr 1fr',
      gap: 4
    }
  }, (inspectTab === 'source' || inspectTab === 'side') && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("img", {
    src: imgSrc(inspectedItem),
    alt: "source",
    style: {
      width: '100%',
      borderRadius: 6,
      background: '#f1f5f9'
    },
    onError: function onError(e) {
      e.target.style.background = '#e2e8f0';
    }
  }), (inspectTab === 'overlay' || inspectTab === 'side') && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      position: 'relative'
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("img", {
    src: imgSrc(inspectedItem),
    alt: "base",
    style: {
      width: '100%',
      borderRadius: 6,
      background: '#f1f5f9'
    },
    onError: function onError(e) {
      e.target.style.background = '#e2e8f0';
    }
  }), overlayUrl(inspectedItem) && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("img", {
    src: overlayUrl(inspectedItem),
    alt: "overlay",
    style: {
      position: 'absolute',
      inset: 0,
      width: '100%',
      height: '100%',
      objectFit: 'contain',
      mixBlendMode: 'multiply',
      opacity: 0.6
    }
  }), !overlayUrl(inspectedItem) && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'rgba(0,0,0,0.25)',
      borderRadius: 6
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
    style: {
      color: '#fff',
      fontSize: 11,
      background: 'rgba(0,0,0,0.5)',
      padding: '4px 10px',
      borderRadius: 6
    }
  }, inspectedItem.demo_mode ? 'Demo — no real overlay' : 'Overlay unavailable')))), inspectedItem.class_ratios && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      marginTop: 10
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#334155',
      marginBottom: 4
    }
  }, "Class Breakdown"), Object.entries(inspectedItem.class_ratios).sort(function (_ref21, _ref22) {
    var _ref23 = _slicedToArray(_ref21, 2),
      a = _ref23[1];
    var _ref24 = _slicedToArray(_ref22, 2),
      b = _ref24[1];
    return b - a;
  }).map(function (_ref25) {
    var _ref26 = _slicedToArray(_ref25, 2),
      cls = _ref26[0],
      ratio = _ref26[1];
    return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      key: cls,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        marginBottom: 3
      }
    }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
      style: {
        display: 'inline-block',
        width: 8,
        height: 8,
        borderRadius: 2,
        background: CLASS_COLORS[cls] || DEFAULT_COLOR,
        flexShrink: 0
      }
    }), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
      style: {
        fontSize: 10,
        color: '#64748b',
        width: 65,
        textAlign: 'right'
      }
    }, cls), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      style: {
        flex: 1,
        height: 6,
        background: '#e2e8f0',
        borderRadius: 3,
        overflow: 'hidden'
      }
    }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      style: {
        height: '100%',
        width: "".concat(ratio * 100, "%"),
        background: CLASS_COLORS[cls] || DEFAULT_COLOR,
        borderRadius: 3
      }
    })), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
      style: {
        fontSize: 10,
        color: '#334155',
        width: 32,
        textAlign: 'right'
      }
    }, (ratio * 100).toFixed(0), "%"));
  })), inspectedItem.object_counts && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      marginTop: 10
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#334155',
      marginBottom: 4
    }
  }, "Object Counts"), Object.entries(inspectedItem.object_counts).sort(function (_ref27, _ref28) {
    var _ref29 = _slicedToArray(_ref27, 2),
      a = _ref29[1];
    var _ref30 = _slicedToArray(_ref28, 2),
      b = _ref30[1];
    return b - a;
  }).map(function (_ref31) {
    var _ref32 = _slicedToArray(_ref31, 2),
      cls = _ref32[0],
      count = _ref32[1];
    return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      key: cls,
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        fontSize: 11,
        color: '#64748b',
        marginBottom: 2
      }
    }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", null, cls), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
      style: {
        fontWeight: 600,
        color: '#334155'
      }
    }, count));
  })), inspectedItem.detections && inspectedItem.detections.length > 0 && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      marginTop: 10
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: '#334155',
      marginBottom: 4
    }
  }, "Detections"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      maxHeight: 100,
      overflowY: 'auto'
    }
  }, inspectedItem.detections.map(function (det, i) {
    return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      key: i,
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        fontSize: 10,
        color: '#64748b',
        marginBottom: 2
      }
    }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", null, det.label), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
      style: _objectSpread(_objectSpread({}, S.badge), {}, {
        background: det.confidence > 0.7 ? '#dcfce7' : '#fef9c3',
        color: det.confidence > 0.7 ? '#166534' : '#92400e'
      })
    }, (det.confidence * 100).toFixed(0), "%"));
  }))), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      marginTop: 8,
      fontSize: 10,
      color: '#94a3b8'
    }
  }, inspectedItem.image_id, inspectedItem.latitude != null && " \xB7 ".concat(inspectedItem.latitude.toFixed(4), ", ").concat((_inspectedItem$longit = inspectedItem.longitude) === null || _inspectedItem$longit === void 0 ? void 0 : _inspectedItem$longit.toFixed(4))), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      marginTop: 8
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    style: _objectSpread(_objectSpread({}, S.link), {}, {
      marginLeft: 0,
      opacity: inspectIdx > 0 ? 1 : 0.3
    }),
    onClick: function onClick() {
      return inspectIdx > 0 && setInspectIdx(inspectIdx - 1);
    },
    disabled: inspectIdx === 0
  }, "\u2190 Prev"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    style: S.link,
    onClick: function onClick() {
      setInspectIdx(null);
      setView('gallery');
    }
  }, "Back to Gallery"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    style: _objectSpread(_objectSpread({}, S.link), {}, {
      marginLeft: 0,
      opacity: inspectIdx < results.length - 1 ? 1 : 0.3
    }),
    onClick: function onClick() {
      return inspectIdx < results.length - 1 && setInspectIdx(inspectIdx + 1);
    },
    disabled: inspectIdx === results.length - 1
  }, "Next \u2192"))));
  return {
    contentComponent: contentComponent
  };
};

/***/ },

/***/ "../../../packages/curio.streetvision@1/sources/hfCvInferenceLifecycle.tsx"
/*!*********************************************************************************!*\
  !*** ../../../packages/curio.streetvision@1/sources/hfCvInferenceLifecycle.tsx ***!
  \*********************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   useHfCvInferenceLifecycle: () => (/* binding */ useHfCvInferenceLifecycle)
/* harmony export */ });
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! react */ "react");
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(react__WEBPACK_IMPORTED_MODULE_0__);
var _curio;
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: !0, configurable: !0, writable: !0 }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == _typeof(i) ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != _typeof(t) || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r || "default"); if ("object" != _typeof(i)) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
function _createForOfIteratorHelper(r, e) { var t = "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (!t) { if (Array.isArray(r) || (t = _unsupportedIterableToArray(r)) || e && r && "number" == typeof r.length) { t && (r = t); var _n = 0, F = function F() {}; return { s: F, n: function n() { return _n >= r.length ? { done: !0 } : { done: !1, value: r[_n++] }; }, e: function e(r) { throw r; }, f: F }; } throw new TypeError("Invalid attempt to iterate non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); } var o, a = !0, u = !1; return { s: function s() { t = t.call(r); }, n: function n() { var r = t.next(); return a = r.done, r; }, e: function e(r) { u = !0, o = r; }, f: function f() { try { a || null == t["return"] || t["return"](); } finally { if (u) throw o; } } }; }
function _toConsumableArray(r) { return _arrayWithoutHoles(r) || _iterableToArray(r) || _unsupportedIterableToArray(r) || _nonIterableSpread(); }
function _nonIterableSpread() { throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _iterableToArray(r) { if ("undefined" != typeof Symbol && null != r[Symbol.iterator] || null != r["@@iterator"]) return Array.from(r); }
function _arrayWithoutHoles(r) { if (Array.isArray(r)) return _arrayLikeToArray(r); }
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
function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }

/**
 * HuggingFace CV Inference lifecycle.
 *
 * Receives a GEODATAFRAME of image points (each feature carrying
 * `image_url`, plus optional `latitude` / `longitude` / `pano_id`) from
 * any upstream node — typically the Street View Fetcher, but also Data
 * Loading (CSV of URLs), or any Python computation that emits the same
 * shape. Runs HuggingFace segmentation / detection inference on each
 * image, polls progress, and emits a JSON results payload downstream.
 *
 * Model + class config UI adapted from the model-selection and class-picker
 * sections of
 *   utk_curio/frontend/urban-workflows/src/adapters/node/streetVisionLifecycle.tsx
 * in ManeeshJupalle/curio (feat/street-vision-cv-analysis, #120).
 */

// See streetViewFetcherLifecycle for the rationale on runtime URL resolution.
var API_BASE = "".concat(typeof window !== 'undefined' && ((_curio = window.curio) === null || _curio === void 0 ? void 0 : _curio.backendUrl) || '', "/api/streetvision");
var CLASS_SUGGESTIONS = ['building', 'road', 'sidewalk', 'vegetation', 'pole', 'fence', 'wall', 'traffic sign'];
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
    background: 'linear-gradient(135deg,#ec4899,#f472b6)',
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
    width: '100%'
  },
  btnPrimary: {
    background: 'linear-gradient(135deg,#ec4899,#db2777)',
    color: '#fff'
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
  chip: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    padding: '3px 8px',
    borderRadius: 12,
    fontSize: 11,
    cursor: 'pointer',
    border: '1px solid #e2e8f0',
    background: '#fff'
  },
  chipActive: {
    background: '#fdf2f8',
    borderColor: '#f9a8d4',
    color: '#be185d'
  },
  progressOuter: {
    height: 6,
    background: '#e2e8f0',
    borderRadius: 3,
    overflow: 'hidden',
    marginTop: 6
  },
  progressFill: {
    height: '100%',
    background: 'linear-gradient(90deg,#ec4899,#f472b6)',
    borderRadius: 3,
    transition: 'width 0.3s'
  },
  err: {
    color: '#991b1b',
    background: '#fef2f2',
    border: '1px solid #fecaca',
    borderRadius: 6,
    padding: '6px 8px',
    fontSize: 11
  },
  warn: {
    color: '#92400e',
    background: '#fef9c3',
    border: '1px solid #fde68a',
    borderRadius: 6,
    padding: '6px 8px',
    fontSize: 11
  }
};

// Pull the image list out of whatever shape the upstream node emitted. We
// accept:
//   1. Curio's GEODATAFRAME wrapper: `{ data: FeatureCollection, dataType: 'geodataframe' }`
//   2. A bare FeatureCollection
//   3. An object with an `images` array (forward compat with custom shapes)
function extractImages(input) {
  if (!input) return [];
  // GEODATAFRAME wrapper
  if (_typeof(input) === 'object' && input.dataType === 'geodataframe' && input.data) {
    return extractImages(input.data);
  }
  // Bare FeatureCollection
  if ((input === null || input === void 0 ? void 0 : input.type) === 'FeatureCollection' && Array.isArray(input.features)) {
    return input.features.map(function (f) {
      var _f$geometry, _props$longitude, _props$latitude;
      var props = (f === null || f === void 0 ? void 0 : f.properties) || {};
      var coords = f === null || f === void 0 || (_f$geometry = f.geometry) === null || _f$geometry === void 0 ? void 0 : _f$geometry.coordinates;
      var lon = (_props$longitude = props.longitude) !== null && _props$longitude !== void 0 ? _props$longitude : Array.isArray(coords) ? coords[0] : undefined;
      var lat = (_props$latitude = props.latitude) !== null && _props$latitude !== void 0 ? _props$latitude : Array.isArray(coords) ? coords[1] : undefined;
      return {
        image_id: props.image_id || props.pano_id || undefined,
        pano_id: props.pano_id,
        image_url: props.image_url,
        latitude: lat,
        longitude: lon
      };
    }).filter(function (x) {
      return !!x.image_url;
    });
  }
  if (Array.isArray(input === null || input === void 0 ? void 0 : input.images)) {
    return input.images;
  }
  return [];
}
var useHfCvInferenceLifecycle = function useHfCvInferenceLifecycle(data, nodeState) {
  // ── Health ──────────────────────────────────────────────────────────
  var _useState = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(false),
    _useState2 = _slicedToArray(_useState, 2),
    backendUp = _useState2[0],
    setBackendUp = _useState2[1];
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    var check = function check() {
      fetch("".concat(API_BASE, "/health")).then(function (r) {
        return r.json();
      }).then(function () {
        return setBackendUp(true);
      })["catch"](function () {
        return setBackendUp(false);
      });
    };
    check();
    var iv = setInterval(check, 10000);
    return function () {
      return clearInterval(iv);
    };
  }, []);

  // ── Upstream images ────────────────────────────────────────────────
  var _useState3 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)([]),
    _useState4 = _slicedToArray(_useState3, 2),
    images = _useState4[0],
    setImages = _useState4[1];
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    var extracted = extractImages(data.input);
    setImages(extracted);
  }, [data.input]);

  // ── Model picker ───────────────────────────────────────────────────
  var _useState5 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)('segmentation'),
    _useState6 = _slicedToArray(_useState5, 2),
    task = _useState6[0],
    setTask = _useState6[1];
  var _useState7 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)('cityscapes'),
    _useState8 = _slicedToArray(_useState7, 2),
    query = _useState8[0],
    setQuery = _useState8[1];
  var _useState9 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)([]),
    _useState0 = _slicedToArray(_useState9, 2),
    models = _useState0[0],
    setModels = _useState0[1];
  var _useState1 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(false),
    _useState10 = _slicedToArray(_useState1, 2),
    modelsLoading = _useState10[0],
    setModelsLoading = _useState10[1];
  var _useState11 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState12 = _slicedToArray(_useState11, 2),
    modelsError = _useState12[0],
    setModelsError = _useState12[1];
  var _useState13 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState14 = _slicedToArray(_useState13, 2),
    selectedModel = _useState14[0],
    setSelectedModel = _useState14[1];
  var _useState15 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(true),
    _useState16 = _slicedToArray(_useState15, 2),
    autoPick = _useState16[0],
    setAutoPick = _useState16[1];
  var userPickedRef = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)(false);
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    if (query.length < 2) return;
    var t = setTimeout(function () {
      setModelsLoading(true);
      setModelsError(null);
      fetch("".concat(API_BASE, "/models/search?task=").concat(task, "&query=").concat(encodeURIComponent(query))).then(/*#__PURE__*/function () {
        var _ref = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee(r) {
          var d;
          return _regenerator().w(function (_context) {
            while (1) switch (_context.n) {
              case 0:
                _context.n = 1;
                return r.json()["catch"](function () {
                  return {};
                });
              case 1:
                d = _context.v;
                if (r.ok) {
                  _context.n = 2;
                  break;
                }
                throw new Error(d.hint ? "".concat(d.error, ": ").concat(d.hint) : d.error || "HTTP ".concat(r.status));
              case 2:
                return _context.a(2, d);
            }
          }, _callee);
        }));
        return function (_x) {
          return _ref.apply(this, arguments);
        };
      }()).then(function (d) {
        var _d$models;
        var list = (_d$models = d.models) !== null && _d$models !== void 0 ? _d$models : [];
        setModels(list);
        if (autoPick && !userPickedRef.current && list.length > 0) {
          var top = list[0];
          setSelectedModel({
            model_id: top.model_id,
            model_type: task,
            name: top.name,
            description: ''
          });
        }
      })["catch"](function (e) {
        setModels([]);
        setModelsError((e === null || e === void 0 ? void 0 : e.message) || String(e));
      })["finally"](function () {
        return setModelsLoading(false);
      });
    }, 400);
    return function () {
      return clearTimeout(t);
    };
  }, [task, query, autoPick]);
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    userPickedRef.current = false;
  }, [task]);

  // ── Target classes ─────────────────────────────────────────────────
  var _useState17 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)([]),
    _useState18 = _slicedToArray(_useState17, 2),
    selectedClasses = _useState18[0],
    setSelectedClasses = _useState18[1];
  var toggleClass = function toggleClass(cls) {
    setSelectedClasses(function (prev) {
      return prev.includes(cls) ? prev.filter(function (c) {
        return c !== cls;
      }) : [].concat(_toConsumableArray(prev), [cls]);
    });
  };
  var csvInputRef = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)(null);
  var _useState19 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState20 = _slicedToArray(_useState19, 2),
    csvStatus = _useState20[0],
    setCsvStatus = _useState20[1];
  var handleCsvImport = function handleCsvImport(file) {
    setCsvStatus(null);
    var reader = new FileReader();
    reader.onerror = function () {
      return setCsvStatus({
        kind: 'err',
        msg: 'Could not read file.'
      });
    };
    reader.onload = function (e) {
      try {
        var _e$target$result, _e$target;
        var text = String((_e$target$result = (_e$target = e.target) === null || _e$target === void 0 ? void 0 : _e$target.result) !== null && _e$target$result !== void 0 ? _e$target$result : '').replace(/\r/g, '');
        var lines = text.split('\n').map(function (l) {
          return l.split(',')[0].trim();
        }).filter(Boolean);
        if (lines.length === 0) {
          setCsvStatus({
            kind: 'err',
            msg: 'CSV is empty.'
          });
          return;
        }
        var headerHints = ['class', 'classes', 'label', 'labels', 'name', 'category'];
        var skipHeader = headerHints.includes(lines[0].toLowerCase());
        var candidates = (skipHeader ? lines.slice(1) : lines).map(function (s) {
          return s.replace(/^["']|["']$/g, '').trim();
        }).filter(function (s) {
          return s.length > 0 && s.length <= 64;
        });
        var existingLower = new Set(selectedClasses.map(function (c) {
          return c.toLowerCase();
        }));
        var seenLower = new Set();
        var fresh = [];
        var _iterator = _createForOfIteratorHelper(candidates),
          _step;
        try {
          for (_iterator.s(); !(_step = _iterator.n()).done;) {
            var c = _step.value;
            var k = c.toLowerCase();
            if (existingLower.has(k) || seenLower.has(k)) continue;
            seenLower.add(k);
            fresh.push(c);
          }
        } catch (err) {
          _iterator.e(err);
        } finally {
          _iterator.f();
        }
        if (fresh.length === 0) {
          setCsvStatus({
            kind: 'ok',
            msg: 'No new classes to import.'
          });
          return;
        }
        setSelectedClasses(function (prev) {
          return [].concat(_toConsumableArray(prev), fresh);
        });
        setCsvStatus({
          kind: 'ok',
          msg: "Imported ".concat(fresh.length, " class").concat(fresh.length > 1 ? 'es' : '', ".")
        });
      } catch (err) {
        setCsvStatus({
          kind: 'err',
          msg: "Parse error: ".concat((err === null || err === void 0 ? void 0 : err.message) || 'unknown', ".")
        });
      }
    };
    reader.readAsText(file);
  };

  // ── Job lifecycle ──────────────────────────────────────────────────
  var _useState21 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)('config'),
    _useState22 = _slicedToArray(_useState21, 2),
    view = _useState22[0],
    setView = _useState22[1];
  var _useState23 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState24 = _slicedToArray(_useState23, 2),
    jobId = _useState24[0],
    setJobId = _useState24[1];
  var _useState25 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(0),
    _useState26 = _slicedToArray(_useState25, 2),
    processed = _useState26[0],
    setProcessed = _useState26[1];
  var _useState27 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(0),
    _useState28 = _slicedToArray(_useState27, 2),
    totalImages = _useState28[0],
    setTotalImages = _useState28[1];
  var _useState29 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState30 = _slicedToArray(_useState29, 2),
    stageMessage = _useState30[0],
    setStageMessage = _useState30[1];
  var _useState31 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState32 = _slicedToArray(_useState31, 2),
    jobError = _useState32[0],
    setJobError = _useState32[1];
  var _useState33 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)([]),
    _useState34 = _slicedToArray(_useState33, 2),
    results = _useState34[0],
    setResults = _useState34[1];
  var pollRef = (0,react__WEBPACK_IMPORTED_MODULE_0__.useRef)();
  var stopPolling = (0,react__WEBPACK_IMPORTED_MODULE_0__.useCallback)(function () {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = undefined;
    }
  }, []);
  var pushResults = (0,react__WEBPACK_IMPORTED_MODULE_0__.useCallback)(function (jobResults, jid) {
    var payload = {
      type: 'street_vision_results',
      job_id: jid,
      model_type: task,
      total_images: jobResults.length,
      results: jobResults
    };
    data.outputCallback(data.nodeId, JSON.stringify(payload));
    nodeState.setOutput({
      code: 'success',
      content: ''
    });
  }, [data, task, nodeState]);
  var handleRun = (0,react__WEBPACK_IMPORTED_MODULE_0__.useCallback)(function () {
    if (!selectedModel || images.length === 0 || selectedClasses.length === 0) return;
    setJobError(null);
    setResults([]);
    setProcessed(0);
    setTotalImages(images.length);
    setView('running');
    fetch("".concat(API_BASE, "/inference/run"), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        images: images,
        model: selectedModel,
        classes: {
          classes: selectedClasses,
          source: 'prompt'
        }
      })
    }).then(/*#__PURE__*/function () {
      var _ref2 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee2(r) {
        var _yield$r$json, _yield$r$json2;
        var _t, _t2, _t3, _t4, _t5, _t6, _t7, _t8, _t9, _t0;
        return _regenerator().w(function (_context2) {
          while (1) switch (_context2.n) {
            case 0:
              if (r.ok) {
                _context2.n = 11;
                break;
              }
              _t = Error;
              _context2.n = 1;
              return r.json();
            case 1:
              _t5 = _yield$r$json = _context2.v;
              _t4 = _t5 === null;
              if (_t4) {
                _context2.n = 2;
                break;
              }
              _t4 = _yield$r$json === void 0;
            case 2:
              if (!_t4) {
                _context2.n = 3;
                break;
              }
              _t6 = void 0;
              _context2.n = 4;
              break;
            case 3:
              _t6 = _yield$r$json.hint;
            case 4:
              _t3 = _t6;
              if (_t3) {
                _context2.n = 9;
                break;
              }
              _context2.n = 5;
              return r.json();
            case 5:
              _t8 = _yield$r$json2 = _context2.v;
              _t7 = _t8 === null;
              if (_t7) {
                _context2.n = 6;
                break;
              }
              _t7 = _yield$r$json2 === void 0;
            case 6:
              if (!_t7) {
                _context2.n = 7;
                break;
              }
              _t9 = void 0;
              _context2.n = 8;
              break;
            case 7:
              _t9 = _yield$r$json2.error;
            case 8:
              _t3 = _t9;
            case 9:
              _t2 = _t3;
              if (_t2) {
                _context2.n = 10;
                break;
              }
              _t2 = "HTTP ".concat(r.status);
            case 10:
              _t0 = _t2;
              throw new _t(_t0);
            case 11:
              return _context2.a(2, r.json());
          }
        }, _callee2);
      }));
      return function (_x2) {
        return _ref2.apply(this, arguments);
      };
    }()).then(function (d) {
      setJobId(d.job_id);
      pollRef.current = setInterval(function () {
        fetch("".concat(API_BASE, "/inference/results/").concat(d.job_id)).then(function (r) {
          return r.json();
        }).then(function (s) {
          var _s$stage_message, _s$results;
          setProcessed(s.processed);
          setTotalImages(s.total_images);
          setStageMessage((_s$stage_message = s.stage_message) !== null && _s$stage_message !== void 0 ? _s$stage_message : null);
          if ((_s$results = s.results) !== null && _s$results !== void 0 && _s$results.length) setResults(s.results);
          if (s.status === 'completed' || s.status === 'failed') {
            stopPolling();
            if (s.status === 'failed') {
              setJobError(s.error || 'Inference failed.');
            } else {
              setView('done');
              pushResults(s.results, d.job_id);
            }
          }
        })["catch"](function () {
          stopPolling();
          setJobError('Lost connection to backend.');
        });
      }, 2000);
    })["catch"](function (e) {
      return setJobError(e.message || 'Failed to start inference.');
    });
  }, [selectedModel, selectedClasses, images, stopPolling, pushResults]);
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    return function () {
      return stopPolling();
    };
  }, [stopPolling]);
  var pct = totalImages > 0 ? Math.round(processed / totalImages * 100) : 0;
  var allReady = !!selectedModel && selectedClasses.length > 0 && images.length > 0 && backendUp;
  var fmtDl = function fmtDl(n) {
    return typeof n === 'number' ? n >= 1000 ? "".concat((n / 1000).toFixed(n >= 10000 ? 0 : 1), "k") : String(n) : '—';
  };
  var contentComponent = /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.root
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.header
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.logo
  }, "HF"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", null, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.title
  }, "HF CV Inference"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.sub
  }, "HuggingFace segmentation / detection")), view === 'done' && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    style: {
      background: 'none',
      border: 'none',
      color: '#ec4899',
      fontSize: 11,
      fontWeight: 600,
      cursor: 'pointer',
      marginLeft: 'auto'
    },
    onClick: function onClick() {
      return setView('config');
    }
  }, "\u2190 Reconfigure")), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.row
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: _objectSpread(_objectSpread({}, S.dot), {}, {
      background: backendUp ? '#22c55e' : '#ef4444'
    })
  }), backendUp ? 'Backend connected' : 'Backend offline'), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.card
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
    style: {
      fontWeight: 600
    }
  }, "Upstream:"), ' ', images.length > 0 ? "".concat(images.length, " image").concat(images.length > 1 ? 's' : '', " received") : 'waiting for image points…'), view === 'config' && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement((react__WEBPACK_IMPORTED_MODULE_0___default().Fragment), null, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", null, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.label
  }, "1 \xB7 Task"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      display: 'flex',
      gap: 4
    }
  }, ['segmentation', 'detection'].map(function (t) {
    return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
      key: t,
      onClick: function onClick() {
        return setTask(t);
      },
      style: _objectSpread({
        flex: 1,
        padding: '5px 0',
        border: 'none',
        borderRadius: 6,
        fontSize: 11,
        fontWeight: 600,
        cursor: 'pointer'
      }, task === t ? {
        background: 'linear-gradient(135deg,#ec4899,#db2777)',
        color: '#fff'
      } : {
        background: '#f1f5f9',
        color: '#64748b',
        border: '1px solid #e2e8f0'
      })
    }, t.charAt(0).toUpperCase() + t.slice(1));
  }))), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", null, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.label
  }, "2 \xB7 Model"), selectedModel && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: _objectSpread(_objectSpread({}, S.card), {}, {
      background: '#fdf2f8',
      borderColor: '#f9a8d4',
      marginBottom: 6,
      display: 'flex',
      alignItems: 'center',
      gap: 6
    })
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
    style: {
      color: '#22c55e'
    }
  }, "\u2713"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
    style: {
      fontSize: 12,
      color: '#9d174d',
      flex: 1,
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap'
    }
  }, selectedModel.name)), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("input", {
    style: S.input,
    value: query,
    onChange: function onChange(e) {
      userPickedRef.current = false;
      setQuery(e.target.value);
    },
    placeholder: "Search HuggingFace models\u2026"
  }), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("label", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 6,
      marginTop: 6,
      fontSize: 11,
      color: '#475569',
      cursor: 'pointer'
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("input", {
    type: "checkbox",
    checked: autoPick,
    onChange: function onChange(e) {
      setAutoPick(e.target.checked);
      if (e.target.checked) {
        userPickedRef.current = false;
        if (models.length > 0) {
          var top = models[0];
          setSelectedModel({
            model_id: top.model_id,
            model_type: task,
            name: top.name,
            description: ''
          });
        }
      }
    }
  }), "Auto-pick best model (top match by downloads)"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      maxHeight: 130,
      overflowY: 'auto',
      marginTop: 6
    }
  }, modelsLoading && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      fontSize: 11,
      color: '#94a3b8',
      textAlign: 'center',
      padding: 6
    }
  }, "Searching\u2026"), !modelsLoading && modelsError && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: _objectSpread(_objectSpread({}, S.warn), {}, {
      padding: '6px 8px',
      fontSize: 11
    })
  }, modelsError), !modelsLoading && !modelsError && models.length === 0 && query.length >= 2 && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      fontSize: 11,
      color: '#94a3b8',
      textAlign: 'center',
      padding: 6
    }
  }, "No models found"), models.map(function (m) {
    var sel = (selectedModel === null || selectedModel === void 0 ? void 0 : selectedModel.model_id) === m.model_id;
    return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      key: m.model_id,
      onClick: function onClick() {
        userPickedRef.current = true;
        setSelectedModel({
          model_id: m.model_id,
          model_type: task,
          name: m.name,
          description: ''
        });
      },
      style: {
        padding: '5px 7px',
        borderRadius: 6,
        cursor: 'pointer',
        marginBottom: 2,
        background: sel ? '#fdf2f8' : 'transparent',
        border: sel ? '1px solid #f9a8d4' : '1px solid transparent'
      }
    }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        fontSize: 12
      }
    }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
      style: {
        color: '#334155',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
        flex: 1
      }
    }, m.name), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
      style: {
        color: '#94a3b8',
        fontSize: 10,
        marginLeft: 6,
        flexShrink: 0
      }
    }, "\u2B07 ", fmtDl(m.downloads))));
  }))), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", null, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.label
  }, "3 \xB7 Target Classes"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 4
    }
  }, CLASS_SUGGESTIONS.map(function (cls) {
    var active = selectedClasses.includes(cls);
    return /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
      key: cls,
      onClick: function onClick() {
        return toggleClass(cls);
      },
      style: _objectSpread(_objectSpread({}, S.chip), active ? S.chipActive : {})
    }, cls);
  })), selectedClasses.length > 0 && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      fontSize: 10,
      color: '#64748b',
      marginTop: 4
    }
  }, selectedClasses.length, " class", selectedClasses.length > 1 ? 'es' : '', " selected"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      marginTop: 6
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("input", {
    ref: csvInputRef,
    type: "file",
    accept: ".csv,text/csv",
    style: {
      display: 'none'
    },
    onChange: function onChange(e) {
      var _e$target$files;
      var f = (_e$target$files = e.target.files) === null || _e$target$files === void 0 ? void 0 : _e$target$files[0];
      if (f) handleCsvImport(f);
      if (csvInputRef.current) csvInputRef.current.value = '';
    }
  }), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    type: "button",
    onClick: function onClick() {
      var _csvInputRef$current;
      return (_csvInputRef$current = csvInputRef.current) === null || _csvInputRef$current === void 0 ? void 0 : _csvInputRef$current.click();
    },
    style: {
      background: 'none',
      border: 'none',
      padding: 0,
      color: '#ec4899',
      fontSize: 11,
      fontWeight: 500,
      cursor: 'pointer',
      textDecoration: 'underline'
    }
  }, "+ Import CSV"), csvStatus && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
    style: {
      marginLeft: 8,
      fontSize: 10,
      color: csvStatus.kind === 'ok' ? '#16a34a' : '#dc2626'
    }
  }, csvStatus.msg))), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    style: _objectSpread(_objectSpread({}, S.btn), allReady ? S.btnPrimary : S.btnDisabled),
    onClick: handleRun,
    disabled: !allReady,
    title: !backendUp ? 'Backend offline' : images.length === 0 ? 'Connect upstream image source' : selectedModel == null ? 'Pick a model' : selectedClasses.length === 0 ? 'Pick at least one class' : 'Ready'
  }, "\u25B6 Run Inference")), view === 'running' && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.card
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      fontWeight: 600,
      color: '#1a1a2e',
      marginBottom: 8
    }
  }, "Inference in progress"), stageMessage ? /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      color: '#64748b',
      marginBottom: 6,
      fontStyle: 'italic'
    }
  }, stageMessage) : /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      color: '#64748b',
      marginBottom: 6
    }
  }, processed, "/", totalImages, " images\u2026"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.progressOuter
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: _objectSpread(_objectSpread({}, S.progressFill), {}, {
      width: "".concat(pct, "%")
    })
  })), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      textAlign: 'center',
      color: '#94a3b8',
      fontSize: 11,
      marginTop: 8
    }
  }, pct, "%"), jobError && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      marginTop: 10
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.err
  }, jobError), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    style: _objectSpread(_objectSpread(_objectSpread({}, S.btn), S.btnPrimary), {}, {
      marginTop: 8
    }),
    onClick: function onClick() {
      setJobError(null);
      setView('config');
    }
  }, "Back to Config"))), view === 'done' && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement((react__WEBPACK_IMPORTED_MODULE_0___default().Fragment), null, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: _objectSpread(_objectSpread({}, S.card), {}, {
      background: '#f0fdf4',
      borderColor: '#bbf7d0'
    })
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
    style: {
      fontSize: 20
    }
  }, "\u2713"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", null, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      fontWeight: 600,
      color: '#166534',
      fontSize: 13
    }
  }, "Inference Complete"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      fontSize: 11,
      color: '#15803d'
    }
  }, results.length, " images processed")))), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    style: _objectSpread(_objectSpread({}, S.btn), {}, {
      background: '#f0fdf4',
      color: '#166534',
      border: '1px solid #bbf7d0'
    }),
    onClick: function onClick() {
      return jobId && pushResults(results, jobId);
    }
  }, "\u27F3 Re-push Results Downstream")));
  return {
    contentComponent: contentComponent
  };
};

/***/ },

/***/ "../../../packages/curio.streetvision@1/sources/streetViewFetcherLifecycle.tsx"
/*!*************************************************************************************!*\
  !*** ../../../packages/curio.streetvision@1/sources/streetViewFetcherLifecycle.tsx ***!
  \*************************************************************************************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   useStreetViewFetcherLifecycle: () => (/* binding */ useStreetViewFetcherLifecycle)
/* harmony export */ });
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! react */ "react");
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(react__WEBPACK_IMPORTED_MODULE_0__);
function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
var _curio;
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: !0, configurable: !0, writable: !0 }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == _typeof(i) ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != _typeof(t) || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r || "default"); if ("object" != _typeof(i)) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
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

/**
 * Street View Fetcher lifecycle.
 *
 * Owns the *acquisition* half of what was once the monolithic Street Vision
 * node in PR #120: geocode a place name, estimate Street View coverage in
 * its bounding box, and emit a GEODATAFRAME (FeatureCollection of points)
 * downstream. Each feature carries `image_url` so the next node (HF CV
 * Inference, Spatial Join, or anything else) can use the imagery directly.
 *
 * Place-search + coverage-estimate UI adapted from
 *   utk_curio/frontend/urban-workflows/src/adapters/node/streetVisionLifecycle.tsx
 * in ManeeshJupalle/curio (feat/street-vision-cv-analysis, #120).
 */

// Read the host's BACKEND_URL at runtime (set by Curio's main bundle on
// ``window.curio.backendUrl``) instead of inlining ``process.env.BACKEND_URL``
// at the package's build time — the latter bakes a build-host-specific URL
// into the catalog-published bundle and breaks for any deployment that
// doesn't match.
var API_BASE = "".concat(typeof window !== 'undefined' && ((_curio = window.curio) === null || _curio === void 0 ? void 0 : _curio.backendUrl) || '', "/api/streetvision");
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
var useStreetViewFetcherLifecycle = function useStreetViewFetcherLifecycle(data, nodeState) {
  var _useState = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(false),
    _useState2 = _slicedToArray(_useState, 2),
    backendUp = _useState2[0],
    setBackendUp = _useState2[1];

  // Per-session API key. Held in React state only — not persisted to the
  // dataflow spec (would leak when shared) nor to localStorage. User
  // re-enters on reload.
  var _useState3 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(''),
    _useState4 = _slicedToArray(_useState3, 2),
    apiKey = _useState4[0],
    setApiKey = _useState4[1];

  // Configuration
  var _useState5 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(''),
    _useState6 = _slicedToArray(_useState5, 2),
    query = _useState6[0],
    setQuery = _useState6[1];
  var _useState7 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState8 = _slicedToArray(_useState7, 2),
    bbox = _useState8[0],
    setBbox = _useState8[1];
  var _useState9 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState0 = _slicedToArray(_useState9, 2),
    coverage = _useState0[0],
    setCoverage = _useState0[1];
  var _useState1 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(20),
    _useState10 = _slicedToArray(_useState1, 2),
    limit = _useState10[0],
    setLimit = _useState10[1];

  // Run state
  var _useState11 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(false),
    _useState12 = _slicedToArray(_useState11, 2),
    busy = _useState12[0],
    setBusy = _useState12[1];
  var _useState13 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState14 = _slicedToArray(_useState13, 2),
    err = _useState14[0],
    setErr = _useState14[1];
  var _useState15 = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(null),
    _useState16 = _slicedToArray(_useState15, 2),
    resultCount = _useState16[0],
    setResultCount = _useState16[1];

  // Poll the backend health endpoint periodically so the user sees connection
  // status. The API key is supplied per-request from this node's UI, so the
  // backend doesn't need to advertise its key state anymore.
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(function () {
    var check = function check() {
      fetch("".concat(API_BASE, "/health")).then(function (r) {
        setBackendUp(r.ok);
      })["catch"](function () {
        return setBackendUp(false);
      });
    };
    check();
    var iv = setInterval(check, 10000);
    return function () {
      return clearInterval(iv);
    };
  }, []);
  var verifyCoverage = (0,react__WEBPACK_IMPORTED_MODULE_0__.useCallback)(function () {
    if (!query.trim() || !apiKey.trim()) return;
    setErr(null);
    setCoverage(null);
    setBbox(null);
    fetch("".concat(API_BASE, "/data/streetview/search_place?query=").concat(encodeURIComponent(query))).then(/*#__PURE__*/function () {
      var _ref = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee(r) {
        var _yield$r$json;
        var _t, _t2, _t3, _t4, _t5, _t6;
        return _regenerator().w(function (_context) {
          while (1) switch (_context.n) {
            case 0:
              if (r.ok) {
                _context.n = 6;
                break;
              }
              _t = Error;
              _context.n = 1;
              return r.json();
            case 1:
              _t4 = _yield$r$json = _context.v;
              _t3 = _t4 === null;
              if (_t3) {
                _context.n = 2;
                break;
              }
              _t3 = _yield$r$json === void 0;
            case 2:
              if (!_t3) {
                _context.n = 3;
                break;
              }
              _t5 = void 0;
              _context.n = 4;
              break;
            case 3:
              _t5 = _yield$r$json.error;
            case 4:
              _t2 = _t5;
              if (_t2) {
                _context.n = 5;
                break;
              }
              _t2 = "HTTP ".concat(r.status);
            case 5:
              _t6 = _t2;
              throw new _t(_t6);
            case 6:
              return _context.a(2, r.json());
          }
        }, _callee);
      }));
      return function (_x) {
        return _ref.apply(this, arguments);
      };
    }()).then(function (place) {
      if (!place.bbox) throw new Error('No bbox returned');
      // Pad single-address geocodes — Nominatim returns ~10m bboxes for
      // street addresses which collapses all sampled points onto one spot.
      var bb = place.bbox;
      var _bb = bb,
        _bb2 = _slicedToArray(_bb, 4),
        w = _bb2[0],
        s = _bb2[1],
        e = _bb2[2],
        n = _bb2[3];
      if (e - w < 0.005 || n - s < 0.005) {
        var cx = typeof place.lon === 'number' ? place.lon : (w + e) / 2;
        var cy = typeof place.lat === 'number' ? place.lat : (s + n) / 2;
        var pad = 0.005; // ~500 m at city latitudes
        bb = [cx - pad, cy - pad, cx + pad, cy + pad];
      }
      setBbox(bb);
      return fetch("".concat(API_BASE, "/data/streetview/coverage"), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          bbox: bb,
          api_key: apiKey
        })
      });
    }).then(/*#__PURE__*/function () {
      var _ref2 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee2(r) {
        var _yield$r$json2;
        var _t7, _t8, _t9, _t0, _t1, _t10;
        return _regenerator().w(function (_context2) {
          while (1) switch (_context2.n) {
            case 0:
              if (r.ok) {
                _context2.n = 6;
                break;
              }
              _t7 = Error;
              _context2.n = 1;
              return r.json();
            case 1:
              _t0 = _yield$r$json2 = _context2.v;
              _t9 = _t0 === null;
              if (_t9) {
                _context2.n = 2;
                break;
              }
              _t9 = _yield$r$json2 === void 0;
            case 2:
              if (!_t9) {
                _context2.n = 3;
                break;
              }
              _t1 = void 0;
              _context2.n = 4;
              break;
            case 3:
              _t1 = _yield$r$json2.error;
            case 4:
              _t8 = _t1;
              if (_t8) {
                _context2.n = 5;
                break;
              }
              _t8 = "HTTP ".concat(r.status);
            case 5:
              _t10 = _t8;
              throw new _t7(_t10);
            case 6:
              return _context2.a(2, r.json());
          }
        }, _callee2);
      }));
      return function (_x2) {
        return _ref2.apply(this, arguments);
      };
    }()).then(function (d) {
      return setCoverage(d.estimated_count);
    })["catch"](function (e) {
      return setErr(e.message || String(e));
    });
  }, [query, apiKey]);
  var runFetch = (0,react__WEBPACK_IMPORTED_MODULE_0__.useCallback)(function () {
    if (!bbox || !apiKey.trim()) return;
    setBusy(true);
    setErr(null);
    setResultCount(null);
    fetch("".concat(API_BASE, "/data/streetview/fetch"), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        bbox: bbox,
        limit: limit,
        api_key: apiKey
      })
    }).then(/*#__PURE__*/function () {
      var _ref3 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee3(r) {
        var _yield$r$json3;
        var _t11, _t12, _t13, _t14, _t15, _t16;
        return _regenerator().w(function (_context3) {
          while (1) switch (_context3.n) {
            case 0:
              if (r.ok) {
                _context3.n = 6;
                break;
              }
              _t11 = Error;
              _context3.n = 1;
              return r.json();
            case 1:
              _t14 = _yield$r$json3 = _context3.v;
              _t13 = _t14 === null;
              if (_t13) {
                _context3.n = 2;
                break;
              }
              _t13 = _yield$r$json3 === void 0;
            case 2:
              if (!_t13) {
                _context3.n = 3;
                break;
              }
              _t15 = void 0;
              _context3.n = 4;
              break;
            case 3:
              _t15 = _yield$r$json3.error;
            case 4:
              _t12 = _t15;
              if (_t12) {
                _context3.n = 5;
                break;
              }
              _t12 = "HTTP ".concat(r.status);
            case 5:
              _t16 = _t12;
              throw new _t11(_t16);
            case 6:
              return _context3.a(2, r.json());
          }
        }, _callee3);
      }));
      return function (_x3) {
        return _ref3.apply(this, arguments);
      };
    }()).then(function (fc) {
      data.outputCallback(data.nodeId, {
        data: fc,
        dataType: 'geodataframe'
      });
      nodeState.setOutput({
        code: 'success',
        content: ''
      });
      setResultCount(Array.isArray(fc === null || fc === void 0 ? void 0 : fc.features) ? fc.features.length : 0);
    })["catch"](function (e) {
      return setErr(e.message || String(e));
    })["finally"](function () {
      return setBusy(false);
    });
  }, [bbox, limit, apiKey, data, nodeState]);
  var hasKey = apiKey.trim().length > 0;
  var ready = backendUp && hasKey && !!bbox && limit > 0 && !busy;
  var statusColor = backendUp ? '#22c55e' : '#ef4444';
  var statusText = backendUp ? 'Backend connected' : 'Backend offline';
  var contentComponent = /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.root
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.header
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.logo
  }, "SV"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", null, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.title
  }, "Street View Fetcher"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.sub
  }, "Place \u2192 image points"))), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.row
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: _objectSpread(_objectSpread({}, S.dot), {}, {
      background: statusColor
    })
  }), statusText), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", null, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.label
  }, "Google Maps API Key"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("input", {
    style: S.input,
    type: "password",
    value: apiKey,
    onChange: function onChange(e) {
      return setApiKey(e.target.value);
    },
    placeholder: "Paste your Google Maps API key",
    autoComplete: "off",
    spellCheck: false
  }), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      fontSize: 11,
      color: '#64748b',
      marginTop: 4
    }
  }, "Held in memory for this session only \u2014 never saved to the dataflow.")), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", null, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.label
  }, "Place"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("input", {
    style: S.input,
    value: query,
    onChange: function onChange(e) {
      return setQuery(e.target.value);
    },
    onKeyDown: function onKeyDown(e) {
      if (e.key === 'Enter') verifyCoverage();
    },
    placeholder: "e.g. Lincoln Park, Chicago",
    disabled: !hasKey
  })), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: {
      display: 'flex',
      gap: 6
    }
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("input", {
    style: _objectSpread(_objectSpread({}, S.input), {}, {
      width: 80
    }),
    type: "number",
    min: 1,
    max: 200,
    value: limit > 0 ? limit : '',
    onChange: function onChange(e) {
      var v = e.target.value;
      if (v === '') {
        setLimit(0);
        return;
      }
      var n = parseInt(v, 10);
      if (!isNaN(n)) setLimit(n);
    },
    onBlur: function onBlur() {
      if (limit < 1) setLimit(20);else if (limit > 200) setLimit(200);
    },
    title: "Image limit (1\u2013200)"
  }), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    style: _objectSpread(_objectSpread({}, S.btn), {}, {
      width: 'auto',
      flex: 1,
      background: '#f1f5f9',
      color: '#334155',
      border: '1px solid #e2e8f0'
    }),
    onClick: verifyCoverage,
    disabled: !hasKey || !query.trim()
  }, "Verify Coverage")), coverage !== null && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: _objectSpread(_objectSpread({}, S.card), {}, {
      display: 'flex',
      alignItems: 'center',
      gap: 6
    })
  }, /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", {
    style: {
      color: '#22c55e'
    }
  }, "\u2713"), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("span", null, "\u2248", coverage, " panoramas available in this area")), /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("button", {
    style: _objectSpread(_objectSpread({}, S.btn), ready ? S.btnPrimary : S.btnDisabled),
    onClick: runFetch,
    disabled: !ready
  }, busy ? 'Fetching…' : '▶ Fetch Images'), resultCount !== null && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: _objectSpread(_objectSpread({}, S.card), {}, {
      color: '#166534',
      background: '#f0fdf4',
      borderColor: '#bbf7d0'
    })
  }, "\u2713 ", resultCount, " image points emitted downstream"), err && /*#__PURE__*/react__WEBPACK_IMPORTED_MODULE_0___default().createElement("div", {
    style: S.err
  }, err));
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
  !*** ../../../packages/curio.streetvision@1/sources/index.tsx ***!
  \****************************************************************/
__webpack_require__.r(__webpack_exports__);
/* harmony import */ var _streetViewFetcherLifecycle__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! ./streetViewFetcherLifecycle */ "../../../packages/curio.streetvision@1/sources/streetViewFetcherLifecycle.tsx");
/* harmony import */ var _hfCvInferenceLifecycle__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(/*! ./hfCvInferenceLifecycle */ "../../../packages/curio.streetvision@1/sources/hfCvInferenceLifecycle.tsx");
/* harmony import */ var _cvGalleryLifecycle__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(/*! ./cvGalleryLifecycle */ "../../../packages/curio.streetvision@1/sources/cvGalleryLifecycle.tsx");
/**
 * Entry point for the curio.streetvision@1 dynamic lifecycle bundle.
 *
 * Webpack builds this into `../scripts/lifecycles.js` (under the package
 * directory). The `scripts/` subdir is one of the archive validator's
 * allowed top-level dirs, so the bundle survives the catalog install
 * round-trip. When the frontend fetches the installed package list and
 * sees `manifest.lifecycleScript: "scripts/lifecycles.js"`, it loads this
 * bundle via a `<script>` tag injection. The side-effect calls below
 * register each lifecycle against the global registry exposed on
 * `window.curio` at app boot.
 *
 * React, ReactFlow, and the `registerLifecycle` function are externalized
 * — they live on `window` so this bundle stays small and shares Curio's
 * own React instance (so hooks work correctly).
 */





// `window.curio.registerLifecycle` is exposed by Curio's main bundle at boot
// (src/registry/index.ts). We avoid a `declare global` for portability —
// babel-preset-typescript outside the host tsconfig refuses ambient
// declarations.

function registerAll(curio) {
  curio.registerLifecycle('street-view-fetcher', _streetViewFetcherLifecycle__WEBPACK_IMPORTED_MODULE_0__.useStreetViewFetcherLifecycle);
  curio.registerLifecycle('hf-cv-inference', _hfCvInferenceLifecycle__WEBPACK_IMPORTED_MODULE_1__.useHfCvInferenceLifecycle);
  curio.registerLifecycle('cv-gallery', _cvGalleryLifecycle__WEBPACK_IMPORTED_MODULE_2__.useCvGalleryLifecycle);
}
if (typeof window !== 'undefined') {
  var w = window;
  if (w.curio && typeof w.curio.registerLifecycle === 'function') {
    registerAll(w.curio);
  } else {
    var _w$__curioPendingPack;
    // Host hasn't published its registry yet. Stash a callback so the boot
    // sequence can drain pending registrations once `window.curio` lands.
    var pending = (_w$__curioPendingPack = w.__curioPendingPackages__) !== null && _w$__curioPendingPack !== void 0 ? _w$__curioPendingPack : w.__curioPendingPackages__ = [];
    pending.push(registerAll);
  }
}
})();

/******/ 	return __webpack_exports__;
/******/ })()
;
});
//# sourceMappingURL=lifecycles.js.map