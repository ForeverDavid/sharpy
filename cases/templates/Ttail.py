'''
Templates to build T-tail models
S. Maraniello, Oct 2018

classes:
- Ttail_3beam allows to generate general T-tail models with 3-beam. 
- Ttail_canonical:  builds the canonical test case as per 
    Murua et al., Prog. Aerosp. Sci., 71 (2014) 54-84
'''

import h5py as h5
import numpy as np
import configobj
import os
from IPython import embed
import sharpy.utils.algebra as algebra
import sharpy.utils.geo_utils as geo_utils


class Ttail_3beams():
    ''' 
    Produces a relatively general geometry of a 3 beams T-tail.
    By default, quadratic beam elements are used. Three beams, sharing one node,
    are used to model the system. VTP and HPT can be tapered, but they have the 
    same chord at the intersection. The time-step is automatically defined based
    on the HTP root chord, the panelling M and the incoming flow speed.

    Input:
    - M: chordwise panelling of surfaces (same for HTP and VTP)
    - Nv: vertical panelling of VTP. Nv must be divisible by 2.
    - Nh: span-wise panelling of HTP. Nh refers to the full number of
        panels on the HTP (left and right) and must be divisible by 4.
    - Mstar_fact: wake length to chord ratio
    - u_inf: wind-speed
    - rho: air density 
    - chord_htp_root: chord length at the htp-vtp interspection
    - chord_htp_tip: tip chord of the HPT (at the root, vtp and htp)
    - chord_vtp_root: chord at the vtp base.
    - span_htp: total span of the HTP (left and right)
    - height_vtp: vertical distance between first and last node of the vtp. Note
    that, in case of sweep angle, this is not the VTP length.
    - alpha_htp_deg=0.0: HTP incidence in degrees, positive if upward. Note that
    if non-zero, both UVLM grid and structural properties are rotated.
    - sweep_htp_deg=0.0: sweep angle, positive if backward                
    - sweep_vtp_deg=0.0: sweep angle, positive if backward  
    - main_ea: chord-normalised distance of elastic axis from leading edge. Must
    be the same for HTP and VTP
    - alpha_inf_deg: angle of attach of incoming flow [deg]. This is obtained
    rotating the local frame A in which the geometry is defined if 
    rotate_frame_A is True, otherwise the incoming flow is tilted.
    - beta_inf_deg: sideslip angle of incoming flow [deg]. This is obtained
    rotating the local frame A in which the geometry is defined if 
    rotate_frame_A is True, otherwise the incoming flow is tilted.
    - rotate_frame_A: determines whether the angles alpha_inf_deg and 
    beta_inf_deg are obtained through rotation of the T-tail or rotation of
    the incoming flow.

    Usage:
    - generate class instance:
        ws=Ttail_3beams(...)
    - manually define mass/stiffness properties in update_mass_stiff method
    -   def ws.update_mass_stiff:
            ...
    - run:
        ws.clean_test_files()
        ws.update_derived_params()
        ws.generate_fem_file()
        ws.generate_aero_file()
        ws.set_default_config_dict()

    Warning:
    - cambred aerofoils not implemented in the model
    - as the mass/structural properties are not generated by this class, to 
    produce a *fem.h5 input file one needs to manually define the
    update_mass_stiff method. (see Ttail_canonical)
    '''

    def __init__(self,
                M,   # chordwise panelling
                Nv,  # panelling VTP
                Nh,  # panelling HTP (total, not half)
                Mstar_fact,
                u_inf,       # flight cond
                rho,  
                # size
                chord_htp_root,
                chord_htp_tip,
                chord_vtp_root,
                span_htp,
                height_vtp,        
                # elastic axis
                main_ea,            # from LE. 
                # angles
                alpha_htp_deg=0.0, # positive if upward
                sweep_htp_deg=0.0, # positive if backward                
                sweep_vtp_deg=0.0, # positive if backward
                # others
                alpha_inf_deg=0.0,
                beta_inf_deg=0.0,
                rotate_frame_A=True,	 
                route='.',         # saving
                case_name='Ttail'):


        ### parametrisation
        assert Nv%2 != 1,\
                'vertical panelling of VTP must be divisible by 2 (using 3-noded FEs!)'
        assert Nh%4 != 1,\
                'spanwise panelling of full HTP must be divisible by 4 (using 3-noded FEs!)'

        # chordwise
        self.M=M
        # vtp
        self.Nv=Nv
        # htp
        self.Nh=Nh
        self.Nh_semi=Nh//2
        # wake
        self.Mstar_fact=Mstar_fact  # wake chord-wise panel factor

        # beam elements 
        self.n_surfaces=3
        self.num_nodes_elem=3
        self.num_elem_vtp=self.Nv//2
        self.num_elem_htpL=self.Nh_semi//2      # port
        self.num_elem_htpR=self.Nh_semi//2      # starboard
        self.num_elem_tot=self.num_elem_vtp+self.num_elem_htpL+self.num_elem_htpR

        self.num_nodes_vtp =2*self.num_elem_vtp +1
        self.num_nodes_htpL=2*self.num_elem_htpL+1
        self.num_nodes_htpR=2*self.num_elem_htpR+1
        self.num_nodes_tot=2*self.num_elem_vtp+2*self.num_elem_htpL+2*self.num_elem_htpR+1

        ### store input
        self.u_inf=u_inf      # flight cond
        self.rho=rho

        self.chord_htp_root=chord_htp_root
        self.chord_htp_tip=chord_htp_tip
        self.chord_vtp_root=chord_vtp_root
        self.span_htp=span_htp
        self.height_vtp=height_vtp
        self.main_ea=main_ea

        self.alpha_htp_deg=alpha_htp_deg
        self.sweep_htp_deg=sweep_htp_deg
        self.sweep_vtp_deg=sweep_vtp_deg

        # FoR A orientation
        self.alpha_inf_deg=alpha_inf_deg
        self.beta_inf_deg=beta_inf_deg
        self.rotate_frame_A=rotate_frame_A

        if self.rotate_frame_A:
            self.quat=algebra.euler2quat(
                          np.pi/180.*np.array([0.0,alpha_inf_deg,beta_inf_deg]))
            self.u_inf_direction=np.array([1.,0.,0.])
        else:
            self.quat=algebra.euler2quat(np.array([0.,0.,0.]))
            self.u_inf_direction=np.dot(algebra.euler2rot(
                    np.pi/180.*np.array([0.0,alpha_inf_deg,beta_inf_deg])),
                                                            np.array([1.,0.,0.]))

        # time-step
        self.dt=self.chord_htp_root/self.M/self.u_inf

        self.route=route + '/'  
        self.case_name=case_name

        # # Aerofoil shape: root and tip
        # self.root_airfoil_P = 0
        # self.root_airfoil_M = 0
        # self.tip_airfoil_P = 0
        # self.tip_airfoil_M = 0



    def update_fem_prop(self):
        ''' 
        Produce FEM connectivity, coordinates, mapping and BCs.

        Elements are numbered globally starting from:
        - vtp: bottom to top
        - htpL: tip to middle
        - htpR: middle to tip

        The node at which VTP and HPT intersect is number (global) 
            2*num_elem_vtp+1
        '''

        num_nodes_elem=self.num_nodes_elem
        num_elem_vtp=self.num_elem_vtp
        num_elem_htpL=self.num_elem_htpL
        num_elem_htpR=self.num_elem_htpR
        num_elem_tot=self.num_elem_tot

        num_nodes_vtp =self.num_nodes_vtp
        num_nodes_htpL=self.num_nodes_htpL
        num_nodes_htpR=self.num_nodes_htpR
        num_nodes_tot=self.num_nodes_tot


        ### beam number
        # used by both fem and aero (surface_number)
        # for each element (global number) allocate beam
        # vtp:  0
        # htpL: 1
        # htpR: 2
        beam_number=np.zeros((num_elem_tot),dtype=np.int)
        beam_number[            :num_elem_vtp]=0                   # vtp
        beam_number[num_elem_vtp:num_elem_vtp+num_elem_htpL]=1     # htp L
        beam_number[-num_elem_htpR:]=2                             # htp R


        ### Connectivity
        # surface: for each surface, specity the elements global no.
        # global: for each element, specify the local-global node number. 
        conn_loc=np.array([0, 2, 1],dtype=int)

        conn_surf_vtp=[ee for ee in range(num_elem_vtp)]
        conn_surf_htpL=[num_elem_vtp+ee for ee in range(num_elem_htpL)]
        conn_surf_htpR=[num_elem_vtp+num_elem_htpL+ee for ee in range(num_elem_htpR)]

        conn_glob=np.zeros((num_elem_tot,num_nodes_elem),dtype=int)
        # add vtp
        node_here=0
        for ee in conn_surf_vtp:
            conn_glob[ee,:]=node_here+conn_loc
            node_here+=2
        node_intersection=node_here
        # add htp left
        node_here+=1
        node_free_htpL=node_here
        for ee in conn_surf_htpL:#range(num_elem_htpL):
            conn_glob[ee,:]=node_here+conn_loc
            node_here+=2
        conn_glob[num_elem_vtp+num_elem_htpL-1,1]=node_intersection
        node_here-=1
        # add htp right
        for ee in conn_surf_htpR:
            conn_glob[ee,:]=node_here+conn_loc
            node_here+=2
        conn_glob[num_elem_vtp+num_elem_htpL,0]=node_intersection
        node_free_htpR=node_here


        ### Nodal coordinates
        sweep_htp=np.pi/180.*self.sweep_htp_deg
        sweep_vtp=np.pi/180.*self.sweep_vtp_deg
        xv = np.zeros((num_nodes_tot,))
        yv = np.zeros((num_nodes_tot,))
        zv = np.zeros((num_nodes_tot,))
        # vtp
        nnvec=range(num_nodes_vtp)
        zv[nnvec]=np.linspace(0,self.height_vtp,num_nodes_vtp)
        xv[nnvec]=zv[nnvec]*np.tan( sweep_vtp )
        # increment all other nodes
        xv[node_intersection:]=xv[node_intersection]
        zv[node_intersection:]=zv[node_intersection]
        # htpL
        nnvec=[1+node_intersection+nn for nn in range(num_nodes_htpL)]
        nnvec[-1]=node_intersection
        yv[nnvec]=np.linspace(-.5*self.span_htp,0.,num_nodes_htpL)
        xv[nnvec]-=yv[nnvec]*np.tan(sweep_htp)
        # htpR
        nnvec=[node_free_htpR-nn for nn in range(num_nodes_htpR)][::-1]
        nnvec[0]=node_intersection
        yv[nnvec]=np.linspace(0.,.5*self.span_htp,num_nodes_htpR)
        xv[nnvec]+=yv[nnvec]*np.tan(sweep_htp)        


        ### boundary conditions
        boundary_conditions=np.zeros((num_nodes_tot,), dtype=int)
        boundary_conditions[0]=1                     # clamp
        boundary_conditions[node_free_htpL]=-1       # free-end htpL
        boundary_conditions[node_free_htpR]=-1       # free end htpR


        ### Define yB, where yB points to the LE.
        # account for HTP incidence
        frame_of_reference_delta = np.zeros((num_elem_tot, num_nodes_elem, 3))
        for ielem in range(num_elem_tot):
            for inode in range(num_nodes_elem):
                frame_of_reference_delta[ielem, inode, :] = [-1, 0, 0]

        self.frame_of_reference_delta=frame_of_reference_delta
        self.boundary_conditions=boundary_conditions
        self.beam_number=beam_number

        self.conn_loc=conn_loc
        self.conn_surf_vtp=conn_surf_vtp
        self.conn_surf_htpL=conn_surf_htpL
        self.conn_surf_htpR=conn_surf_htpR
        self.conn_glob=conn_glob

        self.x=xv
        self.y=yv
        self.z=zv




    def update_aero_prop(self):
        assert hasattr(self,'conn_glob'),\
                           'Run "update_derived_params" before generating files'

        num_nodes_elem=self.num_nodes_elem
        num_elem_vtp=self.num_elem_vtp
        num_elem_htpL=self.num_elem_htpL
        num_elem_htpR=self.num_elem_htpR
        num_elem_tot=self.num_elem_tot

        num_nodes_vtp =self.num_nodes_vtp
        num_nodes_htpL=self.num_nodes_htpL
        num_nodes_htpR=self.num_nodes_htpR
        num_nodes_tot=self.num_nodes_tot


        ### Generate aerofoil profiles. 
        # only flat plate
        airfoil_distribution=np.zeros((num_elem_tot,3),dtype=np.int)
        Airfoils_surf=[]
        Airfoils_surf.append(np.column_stack(geo_utils.generate_naca_camber(0,2)))
        # # vtp
        # # Airfoils_surf.append(geo_utils.generate_naca_camber(0,2))
        # # Na=1
        # for ee in self.conn_surf_vtp:
        #     for nn_loc in [0,2]:
        #         node_glob=self.conn_glob[ee,nn_loc]
        #          eta=xxx
        #         Airfoils_surf.append(
        #                     np.column_stack(
        #                         geo_utils.interpolate_naca_camber(
        #                                 eta,
        #                                 0,self.root_airfoil_P,
        #                                 self.tip_airfoil_M,self.tip_airfoil_P)))


        ### Define aerodynamic nodes
        aero_node=np.ones((num_nodes_tot,),dtype=bool) 


        ### Define chord-wise panelling
        surface_m=self.M*np.ones((3,),dtype=int)   


        ### Define chord-length, sweep, twist
        chord=np.zeros((num_elem_tot, 3))
        twist=np.zeros((num_elem_tot, 3))
        sweep=np.zeros((num_elem_tot, 3))
        # vtp
        nn_count=0
        for ee in self.conn_surf_vtp:
            for nn in [0,1,2]:
                nn_loc=self.conn_loc[nn]
                eta=np.float(nn_count+nn)/(num_nodes_vtp-1)
                chord[ee,nn_loc]=(1.-eta)*self.chord_vtp_root+eta*self.chord_htp_root  
                sweep[ee,nn_loc]=eta*np.pi/180.*(-self.alpha_htp_deg)
            nn_count+=2
        # htpL
        twist[self.conn_surf_htpL,:]=-np.pi/180.*self.alpha_htp_deg 
        nn_count=0
        for ee in self.conn_surf_htpL:
            for nn in [0,1,2]:
                nn_loc=self.conn_loc[nn]
                eta=np.float(nn_count+nn)/(num_nodes_htpL-1)
                chord[ee,nn_loc]=(1.-eta)*self.chord_htp_tip+eta*self.chord_htp_root
                nn_count+=1
        # htpR
        twist[self.conn_surf_htpR,:]=-np.pi/180.*self.alpha_htp_deg 
        nn_count=0
        for ee in self.conn_surf_htpR:
            for nn in [0,1,2]:
                nn_loc=self.conn_loc[nn]
                eta=np.float(nn_count+nn)/(num_nodes_htpR-1)
                chord[ee,nn_loc]=(1.-eta)*self.chord_htp_root+eta*self.chord_htp_tip            
                nn_count+=1

        ### Define chord elastic axis position
        elastic_axis=self.main_ea*np.ones((num_elem_tot, 3,))

        ### store
        self.Airfoils_surf=Airfoils_surf
        self.airfoil_distribution=airfoil_distribution

        self.aero_node=aero_node
        self.surface_m=surface_m

        self.twist=twist
        self.sweep=sweep
        self.chord=chord
        self.elastic_axis=elastic_axis


    def update_mass_stiff(self):
        '''
        This method can be substituted to produce different wing configs
        '''

        # uniform mass/stiffness on HTP/VTP
        ea,ga=1e7,1e7
        gj, eiy,eiz=1e6,2e5,5e6
        self.stiffness=np.zeros((1, 6, 6))
        self.stiffness[0]=np.diag([ea, ga, ga, gj, eiy, eiz])
        self.mass=np.zeros((1, 6, 6))
        self.mass[0, :, :]=np.diag([1., 1., 1., .1, .1, .1])
        self.elem_stiffness=np.zeros((self.num_elem_tot,), dtype=int)
        self.elem_mass=np.zeros((self.num_elem_tot,), dtype=int)  


    def update_derived_params(self):
        # FEM connectivity, coords definition and mapping
        self.update_fem_prop()
        # Mass/stiffness properties
        self.update_mass_stiff()
        # Aero props
        self.update_aero_prop()


    def generate_fem_file(self):

        assert hasattr(self,'conn_glob'),\
                           'Run "update_derived_params" before generating files'

        with h5.File(self.route+'/'+self.case_name+'.fem.h5','a') as h5file:

            coordinates = h5file.create_dataset(
                'coordinates',data=np.column_stack((self.x, self.y, self.z)))
            conectivities = h5file.create_dataset(
                'connectivities', data=self.conn_glob)
            num_nodes_elem_handle = h5file.create_dataset(
                'num_node_elem', data=self.num_nodes_elem)
            num_nodes_handle = h5file.create_dataset(
                'num_node', data=self.num_nodes_tot)
            num_elem_handle = h5file.create_dataset(
                'num_elem', data=self.num_elem_tot)
            stiffness_db_handle = h5file.create_dataset(
                'stiffness_db', data=self.stiffness)
            stiffness_handle = h5file.create_dataset(
                'elem_stiffness', data=self.elem_stiffness)
            mass_db_handle = h5file.create_dataset(
                'mass_db', data=self.mass)
            mass_handle = h5file.create_dataset(
                'elem_mass', data=self.elem_mass)
            frame_of_reference_delta_handle = h5file.create_dataset(
                'frame_of_reference_delta', data=self.frame_of_reference_delta)
            structural_twist_handle = h5file.create_dataset(
                'structural_twist', data=np.zeros((self.num_nodes_tot,)))
            bocos_handle = h5file.create_dataset(
                'boundary_conditions', data=self.boundary_conditions)
            beam_handle = h5file.create_dataset(
                'beam_number', data=self.beam_number)
            app_forces_handle = h5file.create_dataset(
                'app_forces', data=np.zeros((self.num_nodes_tot,6)))



    def set_default_config_dict(self):
        
        if self.rotate_frame_A:
            alpha_aero=np.pi/180.*self.alpha_inf_deg
            beta_aero=np.pi/180.*self.beta_inf_deg
        else:
            alpha_aero=0.
            beta_aero=0.
        str_u_inf_direction=[str(self.u_inf_direction[cc]) for cc in range(3)]


        config=configobj.ConfigObj()
        config.filename=self.route+'/'+self.case_name+'.solver.txt'

        config['SHARPy']={
                'flow':['BeamLoader', 'AerogridLoader',
                        'StaticCoupled', #'StaticUvlm',
                        'AerogridPlot', 'BeamPlot', 'SaveData'],
                'case': self.case_name, 'route': self.route,          
                'write_screen': 'off', 'write_log': 'on',
                'log_folder': self.route+'/output/',
                'log_file': self.case_name+'.log'}

        config['BeamLoader']={
                'unsteady': 'off',
                'orientation': self.quat}

        config['AerogridLoader']={
                'unsteady': 'off',
                'aligned_grid': 'on',
                'mstar': self.Mstar_fact*self.M,
                'freestream_dir':str_u_inf_direction
                                  }
        config['StaticUvlm']={
              'rho': self.rho,
              'velocity_field_generator':'SteadyVelocityField',
              'velocity_field_input':{
                    'u_inf': self.u_inf,
                    'u_inf_direction':self.u_inf_direction},
              'rollup_dt': self.dt,
              'print_info': 'on',
              'horseshoe': 'off',
              'num_cores': 4,
              'n_rollup' : 0,                    
              'rollup_aic_refresh': 0,
              'rollup_tolerance': 1e-4}

        config['StaticCoupled']={
               'print_info': 'on',
               'max_iter': 50,
               'n_load_steps': 1,
               'tolerance': 1e-6,
               'relaxation_factor': 0.,
               'aero_solver': 'StaticUvlm',
               'aero_solver_settings':{
                            'rho': self.rho,
                            'print_info': 'off',
                            'horseshoe': 'off',
                            'num_cores': 4,
                            'n_rollup': 0,
                            'rollup_dt': self.dt,
                            'rollup_aic_refresh': 1,
                            'rollup_tolerance': 1e-4,
                            'velocity_field_generator': 'SteadyVelocityField',
                            'velocity_field_input': {
                                    'u_inf': self.u_inf,
                                    'u_inf_direction': str_u_inf_direction}},
                #
               'structural_solver': 'NonLinearStatic',
               'structural_solver_settings': {'print_info': 'off',
                                              'max_iterations': 150,
                                              'num_load_steps': 4,
                                              'delta_curved': 1e-5,
                                              'min_delta': 1e-5,
                                              'gravity_on': 'on',
                                              'gravity': 9.754,
                                              'orientation': self.quat},}


        config['LinearUvlm'] = {    'dt': self.dt,
                                            'integr_order': 2,
                                            'density': self.rho,
                                            'remove_predictor': True, 
                                            'use_sparse': True,
                                            'ScalingDict':{'length': 1.,
                                                           'speed':  1.,
                                                           'density':1.}}

        config['AerogridPlot']={'folder': self.route+'/output/',
                                'include_rbm': 'off',
                                'include_applied_forces': 'on',
                                'minus_m_star': 0}

        config['AeroForcesCalculator']={'folder': self.route+'/output/forces',
                                        'write_text_file': 'on',
                                        'text_file_name': self.case_name+'_aeroforces.csv',
                                        'screen_output': 'on',
                                        'unsteady': 'off'}

        config['BeamPlot']={'folder':self.route+'/output/',
                            'include_rbm': 'off',
                            'include_applied_forces': 'on'}

        config['BeamCsvOutput']={'folder': self.route+'/output/',
                                 'output_pos': 'on',
                                 'output_psi': 'on',
                                 'screen_output': 'on'}

        config['SaveData'] = {'folder': self.route+'/output/'}

        config['Modal'] = {'folder': self.route+'/output/',
                           'NumLambda': 60,
                           'print_matrices': 'off',
                           'keep_linear_matrices': 'on',
                           'write_modes_vtk': True,
                           'use_undamped_modes': True}

        config.write()
        self.config=config



    def generate_aero_file(self):

        with h5.File(self.route+'/'+self.case_name+'.aero.h5', 'a') as h5file:
            airfoils_group = h5file.create_group('airfoils')
            # add one airfoil
            for aa in range(len(self.Airfoils_surf)):
                airfoils_group.create_dataset('%d'%aa,data=self.Airfoils_surf[aa])

            chord_input = h5file.create_dataset('chord', data=self.chord)
            dim_attr = chord_input.attrs['units'] = 'm'
            twist_input = h5file.create_dataset('twist', data=self.twist)
            dim_attr=twist_input.attrs['units']='rad'
            sweep_input = h5file.create_dataset('sweep', data=self.sweep)
            dim_attr=sweep_input.attrs['units']='rad'

            # airfoil distribution
            airfoil_distribution_input = h5file.create_dataset(
                'airfoil_distribution', data=self.airfoil_distribution)
            surface_distribution_input = h5file.create_dataset(
                'surface_distribution', data=self.beam_number)
            surface_m_input = h5file.create_dataset(
                'surface_m', data=self.surface_m)
            m_distribution_input = h5file.create_dataset(
                'm_distribution', data='uniform'.encode('ascii', 'ignore'))
            aero_node_input = h5file.create_dataset(
                'aero_node', data=self.aero_node)
            elastic_axis_input = h5file.create_dataset(
                'elastic_axis', data=self.elastic_axis)



    def clean_test_files(self):
        fem_file_name = self.route+'/'+self.case_name+'.fem.h5'
        if os.path.isfile(fem_file_name):
            os.remove(fem_file_name)

        aero_file_name = self.route+'/'+self.case_name+'.aero.h5'
        if os.path.isfile(aero_file_name):
            os.remove(aero_file_name)

        solver_file_name = self.route+'/'+self.case_name+'.solver.txt'
        if os.path.isfile(solver_file_name):
            os.remove(solver_file_name)

        flightcon_file_name = self.route+'/'+self.case_name+'.flightcon.txt'
        if os.path.isfile(flightcon_file_name):
            os.remove(flightcon_file_name)



class Ttail_canonical(Ttail_3beams):
    ''' 
    Produces a model of the Canonical T-tail test case proposed by
        Murua et al.,   Prog. Aerosp. Sci., 71 (2014) 54-84
    starting from the Ttail_3beam class.
    '''

    def __init__(self,
                M,Nv,Nh,Mstar_fact,
                u_inf,rho,
                alpha_htp_deg,
                kv,kh,
                alpha_inf_deg=0.,
                beta_inf_deg=0.,
                rotate_frame_A=True,    
                route='.',case_name='Ttail_can'):

        super().__init__( M=M, Nv=Nv, Nh=Nh, Mstar_fact=Mstar_fact,
                          u_inf=u_inf, rho=rho, 
                        # size
                        chord_htp_root=2.,
                        chord_htp_tip=2.,
                        chord_vtp_root=2.,
                        span_htp=4.*2.,
                        height_vtp=6., 
                        # ea
                        main_ea=.25,
                        # angles
                        alpha_htp_deg=alpha_htp_deg,
                        sweep_htp_deg=0.0,        
                        sweep_vtp_deg=0.0,
                        # flow
                        alpha_inf_deg=alpha_inf_deg,
                        beta_inf_deg=beta_inf_deg,
                        rotate_frame_A=rotate_frame_A,    
                        # other
                        route=route,      
                        case_name=case_name)
        self.kv=kv
        self.kh=kh
        self.main_cg=.35


    def update_mass_stiff(self):
        '''
        This method can be substituted to produce different wing configs.

        Remind: the delta_frame_of_reference is chosen such that the B FoR axis 
        are:
        - xb: along the wing span
        - yb: pointing towards the leading edge
        - zb: accordingly
        '''

        ### mass matrix
        # identical for vtp/htp
        m_unit = 35.
        j_tors = 8.
        pos_cg_b=np.array([0.,self.chord_vtp_root*(self.main_cg-self.main_ea), 0.])
        m_chi_cg=algebra.skew(m_unit*pos_cg_b)
        self.mass=np.zeros((2, 6, 6))
        self.mass[0, :, :]=np.diag([ m_unit, m_unit, m_unit, 
                                                  j_tors, .1*j_tors, .9*j_tors])
        self.mass[0,:3,3:]=+m_chi_cg
        self.mass[0,3:,:3]=-m_chi_cg
        self.elem_mass=np.zeros((self.num_elem_tot,), dtype=int)


        ### stiffness
        ea,ga=1e9,1e9
        # vtp
        Kvtp=np.diag([ea, ga, ga, 1e6*self.kv, 1e7,         1e9])
        # htp
        Khtp=np.diag([ea, ga, ga, 1e7*self.kh, 1e7*self.kh, 1e9])

        self.stiffness=np.zeros((2, 6, 6))
        self.stiffness[0,:,:]=Kvtp
        self.stiffness[1,:,:]=Khtp
        self.elem_stiffness=np.zeros((self.num_elem_tot,), dtype=int)
        self.elem_stiffness[self.conn_surf_vtp] =0
        self.elem_stiffness[self.conn_surf_htpL]=1
        self.elem_stiffness[self.conn_surf_htpR]=1




if __name__=='__main__':

    import os
    os.system('mkdir -p %s' %'./test' )

    ws=Ttail_3beams(M=4,
                    Nv=6,           # panelling VTP
                    Nh=8,           # panelling HTP (total, not half)
                    Mstar_fact=7.,
                    u_inf=30.,      # flight cond
                    rho=1.225,  
                    # size
                    chord_htp_root=2.,
                    chord_htp_tip=2.,
                    chord_vtp_root=2.,
                    span_htp=4.*2.,
                    height_vtp=6., 
                    # ea
                    main_ea=.25,
                    # angles
                    alpha_htp_deg=5.0,  # positive if upward
                    sweep_htp_deg=60.0, # positive if backward                
                    sweep_vtp_deg=30.0, # positive if backward
                    #
                    alpha_inf_deg=0.0,
                    beta_inf_deg=0.0,
                    rotate_frame_A=True,    
                    route='./test/',      
                    case_name='Ttail')
    ws.clean_test_files()
    ws.update_derived_params()
    ws.generate_fem_file()
    ws.generate_aero_file()
    ws.set_default_config_dict()


    wc=Ttail_canonical(
                M=4,Nv=6,Nh=8,Mstar_fact=6,
                u_inf=30.,rho=1.225,
                alpha_htp_deg=2.,
                kv=1.,kh=10.,
                alpha_inf_deg=0.,
                beta_inf_deg=0.,
                rotate_frame_A=True,    
                route='./test/',case_name='Tcanonical')
    wc.clean_test_files()
    wc.update_derived_params()
    wc.generate_fem_file()
    wc.generate_aero_file()
    wc.set_default_config_dict()

