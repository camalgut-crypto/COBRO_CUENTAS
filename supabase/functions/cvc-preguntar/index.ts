// Función "cvc-preguntar": responde preguntas sobre los resúmenes del Módulo Cosechas vs Cobro con Claude.
// - Verifica la sesión del usuario y su perfil (cvc_perfiles) y solo le pasa al modelo las secciones de sus pestañas.
// - Lee el resumen que sube el proceso de carga (bucket "cvc", ia/resumen.json.gz) con la clave de servicio.
// - Límite de preguntas por usuario y día; cada pregunta queda en cvc_preguntas.
// Secret requerido: ANTHROPIC_API_KEY (supabase secrets set ANTHROPIC_API_KEY=...).
// SUPABASE_URL, SUPABASE_ANON_KEY y SUPABASE_SERVICE_ROLE_KEY los pone Supabase automáticamente.
import Anthropic from "npm:@anthropic-ai/sdk";
import { createClient } from "npm:@supabase/supabase-js@2";

const LIMITE_DIARIO = 40;
const SECCIONES: Record<string, string[]> = {
  admin: ["cosecha", "cartera_activa", "primeros_pagos", "cono"],
  gerencia: ["cosecha", "cartera_activa", "primeros_pagos", "cono"],
  cobro: ["cartera_activa", "primeros_pagos"],
  comercial: ["primeros_pagos"],
};
const NOMBRES: Record<string, string> = {
  cosecha: "Cosecha", cartera_activa: "Cartera Activa", primeros_pagos: "Primeros Pagos", cono: "Cono de cobranza",
};
const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const responder = (cuerpo: unknown, status = 200) =>
  new Response(JSON.stringify(cuerpo), { status, headers: { ...CORS, "Content-Type": "application/json" } });

const INSTRUCCIONES = `Usted es el asistente de análisis del Módulo Cosechas vs Cobro de Instacredit Nicaragua.
Responde preguntas de colaboradores de riesgo, gerencia, cobro y comercial sobre la originación de créditos y su cobranza.

Reglas:
- Use solo los datos del bloque <datos>. Si la respuesta no está en esos resúmenes, dígalo con claridad y sugiera qué filtro o pestaña del módulo revisar. No invente cifras.
- Los datos son resúmenes agregados al corte indicado en "fecha_corte"; no hay detalle por crédito ni por cliente.
- Responda en español, con trato de usted, en tono claro, positivo y profesional. Vaya al punto: primero la respuesta, después el dato que la respalda.
- Cite los números con su unidad: montos en córdobas (C$), porcentajes con un decimal, y diga de qué grupo salen.
- Cuando compare grupos, advierta si alguno tiene pocos créditos (menos de 30) porque su porcentaje es poco confiable.
- Respete las definiciones del bloque "definiciones" (por ejemplo, la mora 30+ se calcula sobre el total de créditos del grupo, incluidos los cancelados).
- Texto plano, sin tablas Markdown ni encabezados; puede usar viñetas cortas con guion. Máximo unas 200 palabras salvo que pidan más detalle.`;

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return responder({ error: "Método no permitido" }, 405);

  try {
    const url = Deno.env.get("SUPABASE_URL")!;
    const auth = req.headers.get("Authorization") ?? "";
    // Cliente con la sesión del usuario: solo ve su propio perfil (RLS)
    const usuario = createClient(url, Deno.env.get("SUPABASE_ANON_KEY")!, { global: { headers: { Authorization: auth } } });
    const { data: { user } } = await usuario.auth.getUser();
    if (!user) return responder({ error: "Sesión no válida: vuelva a ingresar." }, 401);
    const { data: perfil } = await usuario.from("cvc_perfiles").select("rol, activo, nombre").eq("id", user.id).maybeSingle();
    if (!perfil?.activo) return responder({ error: "Usuario sin acceso a Cosechas vs Cobro." }, 403);

    const { pregunta, pestana } = await req.json();
    const q = String(pregunta ?? "").trim().slice(0, 500);
    if (!q) return responder({ error: "Escriba una pregunta." }, 400);

    const servicio = createClient(url, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
    const hoy = new Date(); hoy.setUTCHours(0, 0, 0, 0);
    const { count } = await servicio.from("cvc_preguntas").select("id", { count: "exact", head: true })
      .eq("usuario", user.id).gte("creado", hoy.toISOString());
    if ((count ?? 0) >= LIMITE_DIARIO) {
      return responder({ error: `Llegó al límite de ${LIMITE_DIARIO} preguntas por día. Mañana puede seguir preguntando.` }, 429);
    }

    // Resumen de la última carga, recortado a las pestañas del perfil
    const { data: archivo, error: errArchivo } = await servicio.storage.from("cvc").download("ia/resumen.json.gz");
    if (errArchivo || !archivo) return responder({ error: "Todavía no hay datos cargados para responder." }, 503);
    const texto = await new Response(archivo.stream().pipeThrough(new DecompressionStream("gzip"))).text();
    const resumen = JSON.parse(texto);
    const permitidas = SECCIONES[perfil.rol] ?? [];
    const datos: Record<string, unknown> = { fecha_corte: resumen.fecha_corte, definiciones: resumen.definiciones };
    for (const s of permitidas) datos[s] = resumen[s];

    const contexto = `Perfil del usuario: ${perfil.rol}. Pestañas que puede ver: ${permitidas.map((s) => NOMBRES[s]).join(", ")}.` +
      (pestana && NOMBRES[pestana] ? ` Está mirando la pestaña ${NOMBRES[pestana]}.` : "");

    const client = new Anthropic({ apiKey: Deno.env.get("ANTHROPIC_API_KEY") });
    const r = await client.beta.messages.create({
      model: "claude-opus-5-5",
      max_tokens: 16000,
      output_config: { effort: "medium" },
      // Si el modelo declina por un filtro de seguridad, el servidor reintenta la misma solicitud con otro modelo
      betas: ["server-side-fallback-2026-07-01"],
      fallbacks: "default",
      system: [
        { type: "text", text: INSTRUCCIONES },
        // Los datos cambian una vez por carga: quedan en caché entre preguntas del mismo día
        { type: "text", text: `<datos>\n${JSON.stringify(datos)}\n</datos>`, cache_control: { type: "ephemeral" } },
      ],
      messages: [{ role: "user", content: `${contexto}\n\nPregunta: ${q}` }],
    });

    let respuesta = "";
    if (r.stop_reason === "refusal") {
      respuesta = "No puedo responder esa pregunta. Pruebe reformularla en términos de los indicadores del módulo.";
    } else {
      for (const b of r.content) if (b.type === "text") respuesta += b.text;
      if (r.stop_reason === "max_tokens") respuesta += "\n\n(La respuesta quedó incompleta; pida un resumen más corto.)";
    }
    respuesta = respuesta.trim() || "No obtuve una respuesta. Intente de nuevo.";

    await servicio.from("cvc_preguntas").insert({
      usuario: user.id, pregunta: q, respuesta,
      tokens_entrada: (r.usage.input_tokens ?? 0) + (r.usage.cache_read_input_tokens ?? 0) + (r.usage.cache_creation_input_tokens ?? 0),
      tokens_salida: r.usage.output_tokens ?? 0,
    });
    return responder({ respuesta });
  } catch (err) {
    if (err instanceof Anthropic.RateLimitError) {
      return responder({ error: "El servicio de IA está ocupado; intente en un minuto." }, 429);
    }
    if (err instanceof Anthropic.AuthenticationError) {
      return responder({ error: "La llave de la IA no es válida: avise al administrador del módulo." }, 500);
    }
    if (err instanceof Anthropic.APIError) {
      return responder({ error: `La IA respondió con un error (${err.status}). Intente de nuevo.` }, 502);
    }
    return responder({ error: `No se pudo responder: ${(err as Error).message}` }, 500);
  }
});
