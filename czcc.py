import serial.tools.list_ports
from serial import Serial, SerialException
from flask import jsonify
from model.nodeModel import NodeModel
import os
import logging
import time
import threading
import datetime
from serial import SerialException
import binascii

class NodeController:
    def __init__(self):
        from config import SERIAL_PORT, SERIAL_BAUDRATE
        self.SERIAL_PORT = SERIAL_PORT
        self.SERIAL_BAUDRATE = int(os.getenv('SERIAL_BAUDRATE', '115200'))
        self.GATEWAY_ID = os.getenv('GATEWAY_ID', 'G100101')
        self.node_model = NodeModel()
        self.serial_lock = threading.Lock()
        self.pause_sensor_request = threading.Event()

    def decode_hex_response(self,hex_data):
          
          try:
            #remove any hewitspace
            hex_data=hex_data.strip()
            if len(hex_data) % 2!=0:
                    logging.error(f"invalid hex data length: {len(hex_data)}")
                    return None

            #convert byte to hex response
            ascii_response= bytes.fromhex(hex_data).decode('ascii', errors='replace')
            logging.debug(f"decoded ascii response: {ascii_response} ")
            return ascii_response
          except ValueError as e:
              logging.error(f"error decoding hex data:{str(e)}")
              return None

    def encode_message(self, message):
        try:
            hex_message=message.encode('ascii', errors='replace').hex()
            logging.debug(f"original msg: {message}")
            logging.debug(f"encoded hex message{hex_message}")
            return hex_message
        except Exception as e:
              logging.error(f"error encoding mesg {str(e)}")
              return None


         

    def enroll_node(self, data):
        node_id = data.get('nodeId')
        state = data.get('state')

        if not node_id or not state:
            return jsonify({'message': 'Missing required fields'}), 400

        # Check if the node already exists
        if self.node_model.node_exists(node_id):
            return jsonify({'message': 'Node already exists'}), 400

        self.pause_sensor_request.set()  # Pause sensor data requests
        try:
            ser = Serial(self.SERIAL_PORT, self.SERIAL_BAUDRATE, timeout=10)
            logging.info(f"Successfully opened serial port {self.SERIAL_PORT}")
            
            # Clear buffers
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            
            # Format data for P2P transmission using configured gateway ID
            message = f"{node_id}{self.GATEWAY_ID}{state}"
            hex_message = self.encode_message(message)
            
            # Format AT+SEND command with hex data
            at_command = f"AT+PSEND={hex_message}\r\n"
            logging.debug(f"Sending command: {at_command}")
            
            # Send the AT command
            ser.write(at_command.encode('ascii'))
            logging.debug(f"Sending hex data: {hex_message}")
            
            # Wait for response
            max_wait = 20
            start_time = time.time()
            
            while (time.time() - start_time) < max_wait:
                if ser.in_waiting:
                    try:
                        response = ser.readline().decode('ascii').strip()
                        logging.debug(f"Received raw response: {response}")
                        
                        # Check if response is in EVT:RXP2P format
                        if "EVT:RXP2P" in response:
                            # Parse the hex data from the response
                            parts = response.split(':')
                            if len(parts) >= 5:
                                hex_data = parts[4].strip()  # Get the hex data and remove any whitespace
                                logging.debug(f"Extracted hex data: {hex_data}")
                                
                                # Convert hex to ASCII
                                try:
                                    # For your specific case: 4E323031303031473130303130313930
                                    # This should decode to: N201001G10010190
                                    ascii_response = self.decode_hex_response(hex_data)
                                    logging.debug(f"Decoded ASCII response: {ascii_response}")
                                    
                                    # Extract node ID and check if it matches
                                    received_node_id = ascii_response[:7]  # N201001modify the 
                                    received_gateway_id = ascii_response[7:14]  # G100101
                                    received_status = ascii_response[14:]  # 90
                                    
                                    logging.debug(f"Parsed values - Node ID: {received_node_id}, Gateway ID: {received_gateway_id}, Status: {received_status}")
                                    
                                    if received_node_id == node_id and received_status == "90":
                                        result = self.node_model.save_node(node_id, self.GATEWAY_ID)
                                        return jsonify({'message': 'Node enrolled successfully', 'data': result}), 200
                                    elif received_status == "80":
                                        return jsonify({'message': 'Node enrollment rejected by device'}), 400
                                
                                except ValueError as e:
                                    logging.error(f"Error decoding hex data: {str(e)}")
                                    continue
                    
                    except Exception as e:
                        logging.error(f"Error parsing response: {str(e)}")
                        continue
                    
                    
                time.sleep(0.1)
            
            return jsonify({'message': 'Timeout waiting for node response'}), 500
            
        except SerialException as e:
            logging.error(f"Serial port error: {str(e)}")
            return jsonify({'message': f'Serial port error: {str(e)}'}), 500
        except Exception as e:
            logging.error(f"Unexpected error: {str(e)}")
            return jsonify({'message': f'Error enrolling node: {str(e)}'}), 500
        finally:
            if 'ser' in locals():
                ser.close()
            self.pause_sensor_request.clear()  # Resume sensor data requests

    def control_relay(self, data):
        node_id = data.get('nodeId')
        relay_number = data.get('relayNumber')  # Should be 1 or 2
        relay_state = data.get('relayState') # Should be '0' or '1'
        state = data.get('state-code') 

        # Validate inputs
        if not node_id or relay_number not in [1, 2] or relay_state not in ['0', '1']:
            return jsonify({'message': 'Invalid input parameters'}), 400

        try:
            # Open serial connection
            ser = Serial(self.SERIAL_PORT, self.SERIAL_BAUDRATE, timeout=10)
            logging.info(f"Successfully opened serial port {self.SERIAL_PORT}")
            
            # Clear buffers
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            
            # Format relay command (00 for relay1, 01 for relay2)
            relay_code = '00' if relay_number == 1 else '01'
            message = f"{node_id}{self.GATEWAY_ID}{state}{relay_code}{relay_state}"
            hex_message = message.encode('ascii').hex()
            
            # Format AT command
            at_command = f"AT+PSEND={hex_message}\r\n"
            logging.debug(f"Sending command: {at_command}")
            
            # Send command
            ser.write(at_command.encode('ascii'))
            
            # Wait for response with timeout
            start_time = time.time()
            while (time.time() - start_time) < 10:  # 10 second timeout
                if ser.in_waiting:
                    response = ser.readline().decode('ascii').strip()
                    logging.debug(f"Received response: {response}")
                    
                    if "EVT:RXP2P" in response:
                        parts = response.split(':')
                        if len(parts) >= 5:
                            hex_data = parts[4].strip()
                            try:
                                ascii_response = bytes.fromhex(hex_data).decode('ascii')
                                received_node_id = ascii_response[:7]
                                received_status = ascii_response[14:]
                                
                                if received_node_id == node_id:
                                    if received_status == "92":  # Success code
                                        # Update relay state in database
                                        if relay_number == 1:
                                            self.node_model.update_relay_state(node_id, 'relay1_state', relay_state)
                                        else:
                                            self.node_model.update_relay_state(node_id, 'relay2_state', relay_state)
                                        
                                        # Update relay state in local storage
                                        # Retrieve the current state of the node from local storage
                                        current_node = self.node_model.local_storage.get_node(node_id)
                                        
                                        # Update the relay state without resetting the other relay state
                                        node_dict = {
                                            'node_id': node_id,
                                            'relay1_state': relay_state if relay_number == 1 else current_node.get('relay1_state', '0'),
                                            'relay2_state': relay_state if relay_number == 2 else current_node.get('relay2_state', '0'),
                                            'timestamp': datetime.utcnow().isoformat()
                                        }
                                        self.node_model.local_storage.add_node(node_dict)
                                        return jsonify({
                                            'message': f'Relay {relay_number} state updated successfully',
                                            'nodeId': node_id,
                                            'relayNumber': relay_number,
                                            'state': relay_state
                                        }), 200
                                    elif received_status == "82":  # Error code
                                        return jsonify({'message': 'Relay control rejected by device'}), 400
                                
                            except ValueError as e:
                                logging.error(f"Error decoding response: {str(e)}")
                                continue
                    
                time.sleep(0.1)
            
            return jsonify({'message': 'Timeout waiting for relay response'}), 500
            
        except SerialException as e:
            logging.error(f"Serial port error: {str(e)}")
            return jsonify({'message': f'Serial port error: {str(e)}'}), 500
        except Exception as e:
            logging.error(f"Unexpected error: {str(e)}")
            return jsonify({'message': f'Error controlling relay: {str(e)}'}), 500
        finally:
            if 'ser' in locals():
                ser.close()


    def periodic_sensor_data_request(self):
      while True:
        try:
            if self.pause_sensor_request.is_set():
                logging.debug("sensor request paused")
                if 'ser' in locals():
                    ser.close()     
                if self.serial_lock.locked():
                    self.serial_lock.release()
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
                    if self.pause_sensor_request.is_set():
                        logging.info("Sensor data request paused")
                        break

                    node_id = node['node_id']
                    try:
                        ser = Serial(self.SERIAL_PORT, self.SERIAL_BAUDRATE, timeout=7)
                        logging.info(f"Opened serial port: {self.SERIAL_PORT}")

                        # Format sensor request command
                        message = f"{node_id}{self.GATEWAY_ID}10"
                        hex_message = binascii.hexlify(message.encode('ascii')).decode('ascii')
                        at_command = f"AT+PSEND={hex_message}\r\n"

                        logging.debug(f"Sending sensor request to node {node_id}")
                        logging.debug(f"Command: {at_command}")

                        ser.write(at_command.encode('ascii'))
                        ser.flush()
                        logging.info("Command sent successfully.")

                        start_time = time.time()
                        response_received = False

                        while (time.time() - start_time) < 10:  # 10-second timeout
                            if ser.in_waiting:
                                try:
                                    response = ser.readline().decode('ascii').strip()
                                    logging.debug(f"Received response: {response}")

                                    if "EVT:RXP2P" in response:
                                        parts = response.split(':')
                                        if len(parts) >= 5:
                                            hex_data = parts[4].strip()
                                            try:
                                                binary_data = binascii.unhexlify(hex_data)
                                                sensor_data = binary_data.decode('ascii')

                                                if sensor_data:
                                                    sensor_values = sensor_data[14:]  # Skip node_id and gateway_id
                                                    logging.info(f"Node {node_id} - Sensor Data: {sensor_values}")

                                                    # Optionally store sensor data in local storage
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


    def unenroll_node(self, data):
        self.pause_sensor_request.set()  # Pause sensor data requests
        node_id = data.get('nodeId')
        state = data.get('state')
        
        if not node_id or not state:
            self.pause_sensor_request.clear()  # Resume sensor data requests
            return jsonify({'message': 'Missing required fields'}), 400

        try:
            # Wait for any ongoing sensor requests to complete
            wait_start = time.time()
            while self.serial_lock.locked() and (time.time() - wait_start) < 5:
                time.sleep(1)
            
            # Try to acquire the lock with timeout
            if not self.serial_lock.acquire(timeout=10):
                self.pause_sensor_request.clear()  # Resume sensor data requests
                return jsonify({'message': 'Serial port is busy, please try again later'}), 500
            
            try:
                ser = Serial(self.SERIAL_PORT, self.SERIAL_BAUDRATE, timeout=10)
                logging.info(f"Successfully opened serial port {self.SERIAL_PORT}")
                
                # Clear buffers
                ser.reset_input_buffer()
                ser.reset_output_buffer()
                
                # Format unenroll command
                message = f"{node_id}{self.GATEWAY_ID}{state}"
                hex_message = self.encode_message(message)
                at_command = f"AT+PSEND={hex_message}\r\n"
                logging.debug(f"Sending unenroll command: {at_command}")
                logging.debug(f"Original message: {message}")
                logging.debug(f"Hex message: {hex_message}")
                
                # Send command
                ser.write(at_command.encode('ascii'))
                ser.flush()
                logging.info("Unenroll command sent")
                
                # Small delay to allow the command to be sent and device to process
                time.sleep(0.5)
                
                # Wait for response
                start_time = time.time()
                response_received = False
                
                while (time.time() - start_time) < 15 and not response_received:  # 15 second timeout
                    if ser.in_waiting:
                        response = ser.readline().decode('ascii').strip()
                        logging.debug(f"Received raw response: {response}")
                        
                        if "EVT:RXP2P" in response:
                            parts = response.split(':')
                            if len(parts) >= 5:
                                hex_data = parts[4].strip()
                                logging.debug(f"Extracted hex data: {hex_data}")
                                
                                try:
                                    ascii_response = self.decode_hex_response(hex_data)
                                    if not ascii_response:
                                        logging.error("Failed to decode hex response")
                                        continue
                                        
                                    logging.debug(f"Decoded ASCII response: {ascii_response}")
                                    
                                    # Extract fields (first 7 chars are gateway_id, next 7 are node_id)
                                    received_gateway_id = ascii_response[:7]
                                    received_node_id = ascii_response[7:14]
                                    received_status = ascii_response[14:]
                                    
                                    logging.debug(f"Parsed response - Gateway ID: {received_gateway_id}, Node ID: {received_node_id}, Status: {received_status}")
                                    
                                    if received_gateway_id == self.GATEWAY_ID and received_node_id == node_id:
                                        if received_status == "97":  # Acknowledge code
                                            response_received = True
                                            # Remove node from database and local storage
                                            self.node_model.objects(node_id=node_id).delete()
                                            self.node_model.local_storage.remove_node(node_id)
                                            return jsonify({'message': 'Node unenrolled successfully'}), 200
                                        elif received_status == "87":  # Error code
                                            response_received = True
                                            return jsonify({'message': 'Node unenrollment rejected by device'}), 400
                                    else:
                                        logging.warning(f"Received unexpected IDs. Expected Gateway: {self.GATEWAY_ID}, Node: {node_id}. Got Gateway: {received_gateway_id}, Node: {received_node_id}")
                                except ValueError as e:
                                    logging.error(f"Error decoding response: {str(e)}")
                                    continue
                    time.sleep(0.1)
                
                if not response_received:
                    logging.warning("No valid response received within timeout period")
                    return jsonify({'message': 'Timeout waiting for node response'}), 500
                
            except SerialException as e:
                logging.error(f"Serial port error: {str(e)}")
                return jsonify({'message': f'Serial port error: {str(e)}'}), 500
            finally:
                if 'ser' in locals():
                    ser.close()
                
        except Exception as e:
            logging.error(f"Unexpected error: {str(e)}")
            return jsonify({'message': f'Error unenrolling node: {str(e)}'}), 500
        finally:
            self.serial_lock.release()
            self.pause_sensor_request.clear()  # Resume sensor data requests


__all__ = ['NodeController']
