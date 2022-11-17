# Copyright 2022 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import avatar
import asyncio
import logging
import grpc

from mobly import test_runner, base_test

from avatar.utils import Address
from avatar.controllers import pandora_device
from pandora.host_pb2 import (
    DiscoverabilityMode, DataTypes, OwnAddressType
)


class ExampleTest(base_test.BaseTestClass):
    def setup_class(self):
        self.pandora_devices = self.register_controller(pandora_device)
        self.dut: pandora_device.PandoraDevice = self.pandora_devices[0]
        self.ref: pandora_device.BumblePandoraDevice = self.pandora_devices[1]

    @avatar.asynchronous
    async def setup_test(self):
        await asyncio.gather(*(x.host.FactoryReset() for x in (self.dut, self.ref)))
        responses = await asyncio.gather(*(x.host.ReadLocalAddress(wait_for_ready=True) for x in (self.dut, self.ref)))
        self.dut.address, self.ref.address = responses[0].address, responses[1].address

    def test_print_addresses(self):
        dut_address = self.dut.address
        self.dut.log.info(f'Address: {dut_address}')
        ref_address = self.ref.address
        self.ref.log.info(f'Address: {ref_address}')

    def test_get_remote_name(self):
        dut_name = self.ref.host.GetRemoteName(address=self.dut.address).name
        self.ref.log.info(f'DUT remote name: {dut_name}')
        ref_name = self.dut.host.GetRemoteName(address=self.ref.address).name
        self.dut.log.info(f'REF remote name: {ref_name}')

    def test_classic_connect(self):
        dut_address = self.dut.address
        self.dut.log.info(f'Address: {dut_address}')
        connection = self.ref.host.Connect(address=dut_address).connection
        dut_name = self.ref.host.GetRemoteName(connection=connection).name
        self.ref.log.info(f'Connected with: "{dut_name}" {dut_address}')
        self.ref.host.Disconnect(connection=connection)

    # Using this decorator allow us to write one `test_le_connect`, and
    # run it multiple time with different parameters.
    # Here we check that no matter the address type we use for both sides
    # the connection still complete.
    @avatar.parameterized([
        (OwnAddressType.PUBLIC, OwnAddressType.PUBLIC),
        (OwnAddressType.PUBLIC, OwnAddressType.RANDOM),
        (OwnAddressType.RANDOM, OwnAddressType.RANDOM),
        (OwnAddressType.RANDOM, OwnAddressType.PUBLIC),
    ])
    def test_le_connect(self, dut_address_type: OwnAddressType, ref_address_type: OwnAddressType):
        self.ref.host.StartAdvertising(legacy=True, connectable=True, own_address_type=ref_address_type)
        peers = self.dut.host.Scan(own_address_type=dut_address_type)
        if ref_address_type == OwnAddressType.PUBLIC:
            scan_response = next((x for x in peers if x.public == self.ref.address))
            connection = self.dut.host.ConnectLE(public=scan_response.public, own_address_type=dut_address_type).connection
        else:
            scan_response = next((x for x in peers if x.random == Address(self.ref.device.random_address)))
            connection = self.dut.host.ConnectLE(random=scan_response.random, own_address_type=dut_address_type).connection
        self.dut.host.Disconnect(connection=connection)

    def test_not_discoverable(self):
        self.dut.host.SetDiscoverabilityMode(mode=DiscoverabilityMode.NOT_DISCOVERABLE)
        peers = self.ref.host.Inquiry(timeout=3.0)
        try:
            assert not next((x for x in peers if x.address == self.dut.address), None)
        except grpc.RpcError as e:
            assert e.code() == grpc.StatusCode.DEADLINE_EXCEEDED

    @avatar.parameterized([
        (DiscoverabilityMode.DISCOVERABLE_LIMITED, ),
        (DiscoverabilityMode.DISCOVERABLE_GENERAL, ),
    ])
    def test_discoverable(self, mode):
        self.dut.host.SetDiscoverabilityMode(mode=mode)
        peers = self.ref.host.Inquiry(timeout=15.0)
        assert next((x for x in peers if x.address == self.dut.address), None)

    @avatar.asynchronous
    async def test_wait_connection(self):
        dut_ref = self.dut.host.WaitConnection(address=self.ref.address)
        ref_dut = await self.ref.host.Connect(address=self.dut.address)
        dut_ref = await dut_ref
        assert ref_dut.connection and dut_ref.connection

    @avatar.asynchronous
    async def test_wait_any_connection(self):
        dut_ref = self.dut.host.WaitConnection()
        ref_dut = await self.ref.host.Connect(address=self.dut.address)
        dut_ref = await dut_ref
        assert ref_dut.connection and dut_ref.connection

    def test_scan_response_data(self):
        self.dut.host.StartAdvertising(
            legacy=True,
            data=DataTypes(
                include_shortened_local_name=True,
                tx_power_level=42,
                incomplete_service_class_uuids16=['FDF0']
            ),
            scan_response_data=DataTypes(include_complete_local_name=True, include_class_of_device=True)
        )

        peers = self.ref.host.Scan()
        scan_response = next((x for x in peers if x.public == self.dut.address))
        assert type(scan_response.data.complete_local_name) == str
        assert type(scan_response.data.shortened_local_name) == str
        assert type(scan_response.data.class_of_device) == int
        assert type(scan_response.data.incomplete_service_class_uuids16[0]) == str
        assert scan_response.data.tx_power_level == 42


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    test_runner.main()
