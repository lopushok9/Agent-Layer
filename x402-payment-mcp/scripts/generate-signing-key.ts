import { generateKeyPair, exportJWK } from "jose";
const {privateKey}=await generateKeyPair("ES256",{extractable:true});
console.log(JSON.stringify(await exportJWK(privateKey)));
