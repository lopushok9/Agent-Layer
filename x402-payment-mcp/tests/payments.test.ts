import assert from "node:assert/strict";
import test from "node:test";
import { requestInit } from "../src/payments.js";

test("a body-less POST builds the same request at preview and after the stored preview round-trip",()=>{
  const atPreview=requestInit({method:"POST"},1000);
  // payment_previews.request_body comes back as null when no body was supplied.
  const atPay=requestInit({method:"POST",body:null},1000);
  for(const init of [atPreview,atPay]){assert.equal(init.body,undefined);assert.equal(init.headers,undefined);assert.equal(init.method,"POST");}
  const withBody=requestInit({method:"POST",body:{q:"btc"}},1000);
  assert.equal(withBody.body,'{"q":"btc"}');assert.deepEqual(withBody.headers,{"content-type":"application/json"});
});
