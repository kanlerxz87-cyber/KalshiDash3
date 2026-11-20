/* Lightweight canvas charts: price line (X=time, Y=price) + liquidity bars. No external deps. */
(function(global){
  "use strict";
  function setup(canvas){
    var dpr = window.devicePixelRatio||1;
    var rect = canvas.getBoundingClientRect();
    canvas.width = Math.max(300, rect.width*dpr); canvas.height = Math.max(180, rect.height*dpr);
    var ctx = canvas.getContext("2d"); ctx.setTransform(dpr,0,0,dpr,0,0);
    return {ctx:ctx, w:rect.width, h:rect.height};
  }
  function drawLine(canvas, points, opts){
    opts = opts||{};
    var s = setup(canvas), ctx=s.ctx, w=s.w, h=s.h;
    ctx.clearRect(0,0,w,h);
    var padL=56, padR=12, padT=12, padB=28;
    var iw=w-padL-padR, ih=h-padT-padB;
    ctx.fillStyle="#9fb0c7"; ctx.font="11px system-ui"; ctx.strokeStyle="#24314d";
    if(!points||points.length<2){
      ctx.fillStyle="#9fb0c7"; ctx.fillText("Not enough data yet — waiting for samples…", padL, padT+20);
      return;
    }
    var t0=points[0].t, t1=points[points.length-1].t;
    var minP=Math.min.apply(null, points.map(function(p){return p.price;})), maxP=Math.max.apply(null, points.map(function(p){return p.price;}));
    if(minP===maxP){ minP=Math.max(0,minP-0.02); maxP=Math.min(1,maxP+0.02); }
    var pad=(maxP-minP)*0.15; minP=Math.max(0,minP-pad); maxP=Math.min(1,maxP+pad);
    function X(t){ return padL + (t1===t0?0:(t-t0)/(t1-t0))*iw; }
    function Y(p){ return padT + (1-(p-minP)/(maxP-minP))*ih; }
    // grid + y labels
    for(var i=0;i<=4;i++){
      var p=minP+(maxP-minP)*i/4, y=Y(p);
      ctx.beginPath(); ctx.moveTo(padL,y); ctx.lineTo(padL+iw,y); ctx.stroke();
      ctx.fillStyle="#9fb0c7"; ctx.fillText("$"+p.toFixed(2), 8, y+4);
    }
    // x labels (first/mid/last)
    ctx.fillStyle="#9fb0c7";
    [0, Math.floor(points.length/2), points.length-1].forEach(function(idx){
      var pt=points[idx]; if(!pt) return;
      var d=new Date(pt.t);
      ctx.fillText(d.toLocaleTimeString(), X(pt.t)-20, h-8);
    });
    // line
    ctx.beginPath(); ctx.strokeStyle="#00b67a"; ctx.lineWidth=2;
    points.forEach(function(pt,i){ var x=X(pt.t), y=Y(pt.price); if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y); });
    ctx.stroke();
    // last point dot + label
    var last=points[points.length-1];
    ctx.fillStyle="#2dd4bf"; ctx.beginPath(); ctx.arc(X(last.t),Y(last.price),4,0,Math.PI*2); ctx.fill();
    ctx.fillStyle="#e8eef7"; ctx.fillText("$"+last.price.toFixed(4), X(last.t)-30, Y(last.price)-8);
    if(opts.title){ ctx.fillStyle="#e8eef7"; ctx.font="bold 12px system-ui"; ctx.fillText(opts.title, padL, padT+2); }
  }
  function drawLiquidity(canvas, orderbook){
    var s=setup(canvas), ctx=s.ctx, w=s.w, h=s.h;
    ctx.clearRect(0,0,w,h);
    var yes=(orderbook&&orderbook.yes_dollars)||[], no=(orderbook&&orderbook.no_dollars)||[];
    if(!yes.length && !no.length){ ctx.fillStyle="#9fb0c7"; ctx.font="12px system-ui"; ctx.fillText("Order book empty (no resting bids).", 12, 24); return; }
    // Merge into YES-price ladder: YES bids at p; NO bids at p => YES ask 1-p with same size.
    var levels={};
    yes.forEach(function(l){ var p=parseFloat(l[0]), c=parseFloat(l[1]); levels[p]=(levels[p]||0)+c; });
    no.forEach(function(l){ var p=1-parseFloat(l[0]); p=Math.round(p*10000)/10000; levels[p]=(levels[p]||0)+parseFloat(l[1]); });
    var prices=Object.keys(levels).map(Number).sort(function(a,b){return a-b;});
    var maxC=Math.max.apply(null, prices.map(function(p){return levels[p];}));
    var padL=56, padB=28, padT=24, iw=w-padL-12, ih=h-padT-padB;
    ctx.fillStyle="#9fb0c7"; ctx.font="11px system-ui";
    ctx.fillText("Contracts available at each YES price (bids only; asks implied as $1 − opposite bid)", padL, 14);
    var bw=Math.max(2, iw/prices.length-2);
    prices.forEach(function(p){
      var bh=(levels[p]/maxC)*ih, x=padL+prices.indexOf(p)*(iw/prices.length), y=padT+ih-bh;
      ctx.fillStyle = p>=0.5 ? "#00b67a" : "#2dd4bf";
      ctx.fillRect(x,y,bw,bh);
      ctx.fillStyle="#9fb0c7"; ctx.fillText("$"+p.toFixed(2), x-4, h-8);
    });
    ctx.fillStyle="#9fb0c7"; ctx.fillText("max "+Math.round(maxC)+" contracts", padL, padT+ih+16);
  }
  global.Charts={drawLine:drawLine, drawLiquidity:drawLiquidity};
})(window);
