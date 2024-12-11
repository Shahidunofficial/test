def periodic_sensor_data_request(self):
    import binascii
    
    while True:
        try:
            if self.pause_sensor_request.is_set():
                logging.debug("Sensor request paused, waiting...")
                time.sleep(0.1)
                continue
                
            if not self.serial_lock.acquire(timeout=0.2):
                logging.debug("Could not acquire serial lock, retrying...")
                continue
                
            try:
                nodes = self.node_model.get_all_nodes()
                
                if not nodes:
                    logging.info("No nodes found in database")
                    time.sleep(5)
                    continue
                
                logging.info("\n=== Sensor Data Request Started ===")
                
                for node in nodes:
                    # More frequent pause checks
                    if self.pause_sensor_request.is_set():
                        logging.info("Sensor data request paused")
                        break
                        
                    node_id = node['node_id']
                    try:
                        ser = Serial(self.SERIAL_PORT, self.SERIAL_BAUDRATE, timeout=7)
                        
                        # Format sensor request command using binascii
                        message = f"{node_id}{self.GATEWAY_ID}10"
                        hex_message = binascii.hexlify(message.encode('ascii')).decode('ascii')
                        at_command = f"AT+PSEND={hex_message}\r\n"
                        
                        # Send command and log
                        logging.info(f"Sending sensor request to node {node_id}")
                        logging.debug(f"Command: {at_command}")
                        
                        ser.write(at_command.encode('ascii'))
                        
                        # Wait for response with timeout
                        start_time = time.time()
                        response_received = False
                        
                        while (time.time() - start_time) < 3:  # Increased timeout to 3 seconds
                            if ser.in_waiting:
                                try:
                                    response = ser.readline().decode('ascii').strip()
                                    if "EVT:RXP2P" in response:
                                        parts = response.split(':')
                                        if len(parts) >= 5:
                                            hex_data = parts[4].strip()
                                            try:
                                                # Use binascii for hex decoding
                                                binary_data = binascii.unhexlify(hex_data)
                                                sensor_data = binary_data.decode('ascii')
                                                
                                                if sensor_data:
                                                    sensor_values = sensor_data[14:]  # Skip node_id and gateway_id
                                                    logging.info(f"Node {node_id} - Sensor Data: {sensor_values}")
                                                    
                                                    # Store sensor data in local storage if needed
                                                    self.node_model.update_sensor_data(node_id, sensor_values)
                                                    
                                                    response_received = True
                                                    break
                                            except binascii.Error as e:
                                                logging.error(f"Binascii error decoding sensor data from node {node_id}: {str(e)}")
                                            except UnicodeDecodeError as e:
                                                logging.error(f"Unicode decode error from node {node_id}: {str(e)}")
                                except UnicodeDecodeError as e:
                                    logging.error(f"Error decoding serial response: {str(e)}")
                                    continue
                            time.sleep(0.1)
                        
                        if not response_received:
                            logging.warning(f"No response received from node {node_id} after timeout")
                        
                    except SerialException as e:
                        logging.error(f"Serial port error in sensor request: {str(e)}")
                        time.sleep(1)
                    finally:
                        if 'ser' in locals():
                            ser.close()
                    
                    # Wait before requesting from next node
                    time.sleep(5)
                
                logging.info("=== Sensor Data Request Completed ===\n")
                
            finally:
                self.serial_lock.release()
                
        except Exception as e:
            logging.error(f"Error in periodic sensor data request: {str(e)}")
            time.sleep(1)
def serial_monitor():
    SERIAL_PORT = os.getenv('SERIAL_PORT', '/dev/ttyUSB0')
    SERIAL_BAUDRATE = int(os.getenv('SERIAL_BAUDRATE', '115200'))
    
    while True:
        try:
            with Serial(SERIAL_PORT, SERIAL_BAUDRATE, timeout=1) as ser:
                print(f"\n=== Serial Monitor Started on {SERIAL_PORT} ===")
                while True:
                    if ser.in_waiting:
                        raw_data = ser.readline()
                        try:
                            print(f">>> {raw_data.decode()}", end='')
                        except:
                            print(f">>> {raw_data}")
                    time.sleep(0.1)
                    
        except Exception as e:
            print(f"Serial monitor error: {str(e)}")
            time.sleep(5)

def main():
    configure_app()
    
    # Start serial monitor in a separate thread
    serial_monitor_thread = threading.Thread(target=serial_monitor, daemon=True)
    serial_monitor_thread.start()
    
    # Start sensor monitoring in a separate thread
    sensor_thread = threading.Thread(target=start_sensor_monitoring, daemon=True)
    sensor_thread.start()
    
    # Start the server
    port = int(os.getenv('PORT', 8080))
    host = os.getenv('HOST', '0.0.0.0')
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    
    print(f"Server starting on {host}:{port}")
    app.run(host=host, port=port, debug=debug)
