"""
webcam-bot
----------
Bot de Telegram que controla una webcam conectada al servidor.

- Botón "📸 Hacer foto" (o /foto): captura una imagen bajo demanda y te
  la envía.
- Vigilancia automática (opcional): revisa la cámara periódicamente y,
  si detecta un perro, te envía la foto sola — sin que pulses nada.
  Se activa/desactiva con el botón "🐶 Vigilancia" o /vigilancia.
- Reset USB (/reset_cam): reinicia la cámara si se queda colgada.

Pensado para desplegarse en Docker en el mismo servidor Linux donde está
conectada la webcam (ver docker-compose.yml para el mapeo del dispositivo).

Arranque: `python -m webcam_bot`.
"""
