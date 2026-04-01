/*
 * SpaceNav Bridge for Onshape
 *
 * Onshape only attempts to connect to the 3Dconnexion driver when
 * navigator.platform reports "Win32". This content script overrides
 * that property so the connection is attempted on Linux too.
 *
 * The override is injected into the page context via a <script> element
 * because content scripts run in an isolated world and cannot modify
 * navigator properties visible to the page.
 */
const script = document.createElement("script");
script.textContent = `Object.defineProperty(Navigator.prototype, "platform", { get: () => "Win32" });`;
document.documentElement.appendChild(script);
script.remove();
