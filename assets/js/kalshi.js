/* Kalshi demo client — public market data needs no key; portfolio/trading needs user-supplied demo key.
   Official bases: https://docs.kalshi.com/getting_started/demo_env , https://docs.kalshi.com/getting_started/api_environments */
(function(global){
  "use strict";
  var DEMO_BASE = "https://external-api.demo.kalshi.co/trade-api/v2";
  var PROD_BASE = "https://external-api.kalshi.com/trade-api/v2";
  var DEMO_WS = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2";

  var CATEGORIES = {
    gas:      { label: "Gas Prices", page: "gas.html",      seriesPrefixes: ["KXAAAGAS","KXAAAGASM","KXGAS"], keywords: ["gas price","gasoline","aaa gas","us gas"] },
    elections:{ label: "Elections",  page: "elections.html",seriesPrefixes: ["KXELECT","KXGOV","KXSENATE","KXHOUSE","KXPRES"], keywords: ["election","governor","senate","congress","midterm","mayor","president","house race","balance of power"] },
    culture:  { label: "Culture",    page: "culture.html",  seriesPrefixes: ["KXOSCAR","KXEMMY","KXGRAMMY","KXMOVIE","KXBOXOFFICE","KXENT"], keywords: ["oscar","emmy","grammy","movie","box office","entertainment","culture","concert","album","best picture"] },
    crypto:   { label: "Crypto",     page: "crypto.html",   seriesPrefixes: ["KXBTC","KXETH","KXCRYPTO","KXSOL","KXXRP"], keywords: ["bitcoin","crypto","btc","ethereum","eth","solana","xrp","dogecoin"] },
    golf:     { label: "Golf",       page: "golf.html",     seriesPrefixes: ["KXPGATOUR","KXPGARYDER","KXPGASOLHEIM","KXGOLF","KXMASTERS"], keywords: ["golf","pga tour","masters","ryder cup","solheim","the open","us open golf"] }
  };

  function base(){ return (global.KALSHI_BASE || DEMO_BASE).replace(/\/$/,""); }
  function setBase(b){ global.KALSHI_BASE = b; try{ localStorage.setItem("kalshi_base", b); }catch(e){} }
  try{ var saved = localStorage.getItem("kalshi_base"); if(saved) global.KALSHI_BASE = saved; }catch(e){}
  if(!global.KALSHI_BASE) global.KALSHI_BASE = DEMO_BASE;

  function num(v, fallback){
    if(v===undefined||v===null||v==="") return fallback;
    var n = Number(v); return isNaN(n) ? fallback : n;
  }
  function dollars(m){
    // Prefer fixed-point dollar strings; fall back to legacy cents.
    if(m.yes_bid_dollars!==undefined) return num(m.yes_bid_dollars, null);
    if(m.yes_bid!==undefined) return num(m.yes_bid, null)/100;
    return null;
  }
  function askDollars(m){
    if(m.yes_ask_dollars!==undefined) return num(m.yes_ask_dollars, null);
    if(m.yes_ask!==undefined) return num(m.yes_ask, null)/100;
    return null;
  }
  function lastDollars(m){
    if(m.last_price_dollars!==undefined) return num(m.last_price_dollars, null);
    if(m.last_price!==undefined) return num(m.last_price, null)/100;
    return null;
  }
  function volume(m){
    if(m.volume_fp!==undefined) return num(m.volume_fp, 0);
    return num(m.volume, 0);
  }
  function volume24h(m){
    if(m.volume_24h_fp!==undefined) return num(m.volume_24h_fp, 0);
    return num(m.volume_24h, 0);
  }
  function openInterest(m){
    if(m.open_interest_fp!==undefined) return num(m.open_interest_fp, 0);
    return num(m.open_interest, 0);
  }

  function normalizeMarket(m){
    var vol = volume(m);
    return {
      ticker: m.ticker || "",
      event_ticker: m.event_ticker || "",
      series_ticker: m.series_ticker || "",
      title: m.title || m.yes_sub_title || "",
      subtitle: m.subtitle || "",
      yes_bid: dollars(m), yes_ask: askDollars(m),
      no_bid: (m.no_bid_dollars!==undefined? num(m.no_bid_dollars,null) : (m.no_bid!==undefined? num(m.no_bid,null)/100 : null)),
      no_ask: (m.no_ask_dollars!==undefined? num(m.no_ask_dollars,null) : (m.no_ask!==undefined? num(m.no_ask,null)/100 : null)),
      last_price: lastDollars(m),
      volume: vol, volume_24h: volume24h(m), open_interest: openInterest(m),
      notional: vol, // $1 per contract
      status: m.status || "", result: (m.result||"").toString().toLowerCase(),
      close_time: m.close_time || "", expiration_time: m.expiration_time || m.expected_expiration_time || "",
      rules_primary: m.rules_primary || "", raw: m
    };
  }

  function classify(m){
    var t = ((m.ticker||"")+" "+(m.series_ticker||"")+" "+(m.title||"")+" "+(m.event_ticker||"")).toLowerCase();
    var series = (m.series_ticker||"").toUpperCase(), ticker = (m.ticker||"").toUpperCase();
    for(var key in CATEGORIES){
      var c = CATEGORIES[key];
      for(var i=0;i<c.seriesPrefixes.length;i++){
        if(series.indexOf(c.seriesPrefixes[i])===0 || ticker.indexOf(c.seriesPrefixes[i])===0) return key;
      }
    }
    for(var k2 in CATEGORIES){
      var c2 = CATEGORIES[k2];
      for(var j=0;j<c2.keywords.length;j++){ if(t.indexOf(c2.keywords[j])!==-1) return k2; }
    }
    return null;
  }

  function fetchJSON(url, opts){
    return fetch(url, opts).then(function(r){
      if(!r.ok) throw new Error("HTTP "+r.status+" for "+url);
      return r.json();
    });
  }

  function getMarkets(params){
    var q = new URLSearchParams();
    Object.keys(params||{}).forEach(function(k){ if(params[k]!==undefined&&params[k]!==null&&params[k]!=="") q.set(k, params[k]); });
    return fetchJSON(base()+"/markets?"+q.toString()).then(function(d){ return (d.markets||[]).map(normalizeMarket); });
  }
  function getMarket(ticker){
    return fetchJSON(base()+"/markets/"+encodeURIComponent(ticker)).then(function(d){ return normalizeMarket(d.market||d); });
  }
  function getEvents(params){
    var q = new URLSearchParams();
    Object.keys(params||{}).forEach(function(k){ if(params[k]!==undefined&&params[k]!==null&&params[k]!=="") q.set(k, params[k]); });
    return fetchJSON(base()+"/events?"+q.toString());
  }
  function getOrderbook(ticker, depth){
    var url = base()+"/markets/"+encodeURIComponent(ticker)+"/orderbook"+(depth?("?depth="+depth):"");
    return fetchJSON(url).then(function(d){ return d.orderbook_fp || d.orderbook || {yes_dollars:[],no_dollars:[]}; });
  }
  function getCandlesticks(seriesTicker, ticker, startTs, endTs, periodInterval){
    var q = new URLSearchParams({start_ts:startTs, end_ts:endTs, period_interval:periodInterval});
    return fetchJSON(base()+"/series/"+encodeURIComponent(seriesTicker)+"/markets/"+encodeURIComponent(ticker)+"/candlesticks?"+q.toString());
  }
  function getTrades(ticker, limit){
    var q = new URLSearchParams({ticker:ticker, limit:limit||100});
    return fetchJSON(base()+"/markets/trades?"+q.toString());
  }
  function getExchangeStatus(){
    return fetchJSON(base()+"/exchange/status");
  }

  // Paginated fetch of open markets (cap pages to stay polite to rate limits).
  function fetchAllOpenMarkets(maxPages){
    maxPages = maxPages||10;
    var out=[], cursor="", pages=0;
    function next(){
      if(pages>=maxPages) return Promise.resolve(out);
      pages++;
      var q = new URLSearchParams({status:"open", limit:200});
      if(cursor) q.set("cursor", cursor);
      return fetchJSON(base()+"/markets?"+q.toString()).then(function(d){
        (d.markets||[]).forEach(function(m){ out.push(normalizeMarket(m)); });
        cursor = d.cursor || "";
        if(!cursor) return out;
        return next();
      });
    }
    return next();
  }

  function rankByDollars(markets){
    return markets.slice().sort(function(a,b){
      if(b.volume!==a.volume) return b.volume-a.volume;
      return b.open_interest-a.open_interest;
    });
  }

  function marketUrl(ticker){
    return "https://kalshi.com/markets/"+ticker.toLowerCase();
  }
  function apiUrl(path){ return base()+path; }

  /* ---- Authenticated (user-supplied demo key, browser-only) ---- */
  function getStoredKey(){ try{ return { id: localStorage.getItem("kalshi_key_id")||"", pem: localStorage.getItem("kalshi_private_key_pem")||"" }; }catch(e){ return {id:"",pem:""}; } }
  function storeKey(id, pem){ try{ localStorage.setItem("kalshi_key_id", id); localStorage.setItem("kalshi_private_key_pem", pem); }catch(e){} }
  function clearKey(){ try{ localStorage.removeItem("kalshi_key_id"); localStorage.removeItem("kalshi_private_key_pem"); }catch(e){} }

  function pemToDer(pem){
    var b64 = pem.replace(/-----BEGIN [^-]+-----/g,"").replace(/-----END [^-]+-----/g,"").replace(/\s+/g,"");
    var bin = atob(b64), bytes = new Uint8Array(bin.length);
    for(var i=0;i<bin.length;i++) bytes[i]=bin.charCodeAt(i);
    return bytes.buffer;
  }
  function signMessage(pem, message){
    var der = pemToDer(pem);
    var isEd = pem.indexOf("BEGIN PRIVATE KEY")!==-1;
    // Try Ed25519 first (Kalshi default), fall back to RSA-PSS.
    return crypto.subtle.importKey("pkcs8", der, {name:"Ed25519"}, false, ["sign"])
      .then(function(k){ return crypto.subtle.sign({name:"Ed25519"}, k, new TextEncoder().encode(message)); })
      .catch(function(){
        return crypto.subtle.importKey("pkcs8", der, {name:"RSA-PSS", hash:"SHA-256"}, false, ["sign"])
          .then(function(k){ return crypto.subtle.sign({name:"RSA-PSS", saltLength:32}, k, new TextEncoder().encode(message)); });
      })
      .then(function(sig){
        var bytes = new Uint8Array(sig), s="";
        for(var i=0;i<bytes.length;i++) s+=String.fromCharCode(bytes[i]);
        return btoa(s);
      });
  }
  function authHeaders(method, pathWithoutQuery){
    var key = getStoredKey();
    if(!key.id || !key.pem) return Promise.reject(new Error("No demo API key stored. Paste your demo key ID + private key on the Portfolio page."));
    var ts = String(Date.now());
    var msg = ts + method.toUpperCase() + pathWithoutQuery;
    return signMessage(key.pem, msg).then(function(sig){
      return { "KALSHI-ACCESS-KEY": key.id, "KALSHI-ACCESS-SIGNATURE": sig, "KALSHI-ACCESS-TIMESTAMP": ts, "Content-Type": "application/json" };
    });
  }
  function authedFetch(path, method, body){
    var pathNoQ = path.split("?")[0];
    return authHeaders(method, pathNoQ).then(function(h){
      return fetch(base()+path, {method:method, headers:h, body: body?JSON.stringify(body):undefined}).then(function(r){
        return r.text().then(function(t){
          var data; try{ data=JSON.parse(t); }catch(e){ data={raw:t}; }
          if(!r.ok){ var err=new Error("HTTP "+r.status+": "+t.slice(0,500)); err.status=r.status; err.data=data; throw err; }
          return data;
        });
      });
    });
  }

  /* ---- Tracked-until-resolved (localStorage) ---- */
  function loadTracked(){ try{ return JSON.parse(localStorage.getItem("kalshi_tracked")||"{}"); }catch(e){ return {}; } }
  function saveTracked(o){ try{ localStorage.setItem("kalshi_tracked", JSON.stringify(o)); }catch(e){} }
  function trackMarket(m){
    var t = loadTracked();
    if(!t[m.ticker]) t[m.ticker] = { ticker:m.ticker, title:m.title, event_ticker:m.event_ticker, series_ticker:m.series_ticker, first_seen:new Date().toISOString(), last_price:m.last_price, status:m.status, result:m.result||"", resolved_at:null };
    else { t[m.ticker].last_price=m.last_price; t[m.ticker].status=m.status; if(m.result) t[m.ticker].result=m.result; }
    saveTracked(t); return t[m.ticker];
  }
  function isResolved(m){
    var r=(m.result||"").toLowerCase();
    return r==="yes"||r==="no"||r==="scalar"||m.status==="finalized"||m.status==="determined";
  }

  global.Kalshi = {
    DEMO_BASE:DEMO_BASE, PROD_BASE:PROD_BASE, DEMO_WS:DEMO_WS, CATEGORIES:CATEGORIES,
    base:base, setBase:setBase, getMarkets:getMarkets, getMarket:getMarket, getEvents:getEvents,
    getOrderbook:getOrderbook, getCandlesticks:getCandlesticks, getTrades:getTrades,
    getExchangeStatus:getExchangeStatus, fetchAllOpenMarkets:fetchAllOpenMarkets,
    rankByDollars:rankByDollars, normalizeMarket:normalizeMarket, classify:classify,
    marketUrl:marketUrl, apiUrl:apiUrl, getStoredKey:getStoredKey, storeKey:storeKey, clearKey:clearKey,
    authedFetch:authedFetch, loadTracked:loadTracked, saveTracked:saveTracked, trackMarket:trackMarket, isResolved:isResolved
  };
})(window);
